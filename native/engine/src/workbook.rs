//! Surgical OOXML updates: unknown parts, drawings and unmodified XML survive verbatim.
use crate::{Cell, Updates};
use anyhow::{Context, Result, bail, ensure};
use roxmltree::{Document, Node};
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Read, Write},
    ops::Range,
    path::Path,
};
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};

fn xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
fn children<'a>(n: Node<'a, 'a>, name: &'a str) -> impl Iterator<Item = Node<'a, 'a>> {
    n.children()
        .filter(move |v| v.is_element() && v.tag_name().name() == name)
}
fn replace(text: &str, mut edits: Vec<(Range<usize>, String)>) -> Result<String> {
    edits.sort_by_key(|e| e.0.start);
    for pair in edits.windows(2) {
        ensure!(pair[0].0.end <= pair[1].0.start, "重叠的工作簿修改");
    }
    let mut out = text.to_string();
    for (r, s) in edits.into_iter().rev() {
        out.replace_range(r, &s);
    }
    Ok(out)
}
fn set_attr(source: &str, key: &str, value: &str) -> Result<String> {
    let doc = Document::parse(source)?;
    let n = doc.root_element();
    let attrs = n
        .attributes()
        .filter(|a| a.name() != key)
        .map(|a| format!(" {}=\"{}\"", a.name(), xml(a.value())))
        .collect::<String>();
    let mut head = format!(
        "<{}{} {}=\"{}\"",
        n.tag_name().name(),
        attrs,
        key,
        xml(value)
    );
    if n.children().next().is_none() {
        head.push_str("/>");
    } else {
        head.push('>');
        let begin = source.find('>').context("XML 起始标签无效")? + 1;
        head.push_str(&source[begin..]);
    }
    Ok(head)
}
fn coord(s: &str) -> Result<(u32, u32)> {
    let mut col = 0u32;
    let mut row = String::new();
    for c in s.chars() {
        if c.is_ascii_uppercase() && row.is_empty() {
            col = col
                .checked_mul(26)
                .and_then(|n| n.checked_add(c as u32 - 'A' as u32 + 1))
                .context("无效列")?;
        } else if c.is_ascii_digit() {
            row.push(c);
        } else {
            bail!("无效单元格：{s}");
        }
    }
    let row: u32 = row.parse()?;
    ensure!(
        (1..=1048576).contains(&row) && (1..=16384).contains(&col),
        "无效单元格：{s}"
    );
    Ok((row, col))
}
fn cell(
    source: Option<Node>,
    address: &str,
    value: Option<&Cell>,
    style: Option<usize>,
    document: &str,
) -> Result<String> {
    if value.is_none() {
        let Some(n) = source else {
            return Ok(match style {
                Some(style) => format!("<c r=\"{address}\" s=\"{style}\"/>"),
                None => format!("<c r=\"{address}\"/>"),
            });
        };
        return if let Some(style) = style {
            set_attr(&document[n.range()], "s", &style.to_string())
        } else {
            Ok(document[n.range()].into())
        };
    }
    let mut attrs = String::new();
    if let Some(n) = source {
        for a in n.attributes() {
            if !["r", "t"].contains(&a.name()) && !(a.name() == "s" && style.is_some()) {
                attrs.push_str(&format!(" {}=\"{}\"", a.name(), xml(a.value())));
            }
        }
    }
    if let Some(style) = style {
        attrs.push_str(&format!(" s=\"{style}\""));
    }
    let body = match value.unwrap() {
        Cell::Number(v) => {
            crate::source::number(v)?;
            format!("<v>{}</v>", xml(v))
        }
        Cell::Text(v) => {
            attrs.push_str(" t=\"inlineStr\"");
            format!("<is><t xml:space=\"preserve\">{}</t></is>", xml(v))
        }
        Cell::Formula(v) => format!("<f>{}</f>", xml(v.trim_start_matches('='))),
        Cell::Blank => String::new(),
    };
    Ok(format!("<c r=\"{address}\"{attrs}>{body}</c>"))
}
fn sheet_xml(
    source: &str,
    update: &crate::SheetUpdate,
    styles: &BTreeMap<(usize, u32), usize>,
) -> Result<String> {
    let doc = Document::parse(source)?;
    let root = doc.root_element();
    let data = children(root, "sheetData")
        .next()
        .context("缺少 sheetData")?;
    let mut all = BTreeMap::<(u32, u32), (String, Option<&Cell>)>::new();
    for address in update.cells.keys().chain(update.formats.keys()) {
        all.insert(
            coord(address)?,
            (address.clone(), update.cells.get(address)),
        );
    }
    for merge in root.descendants().filter(|n| n.has_tag_name("mergeCell")) {
        if let Some(reference) = merge.attribute("ref") {
            let mut parts = reference.split(':');
            let start = coord(parts.next().context("无效合并范围")?)?;
            let end = coord(parts.next().context("无效合并范围")?)?;
            for point in all.keys() {
                if point.0 >= start.0
                    && point.0 <= end.0
                    && point.1 >= start.1
                    && point.1 <= end.1
                    && *point != start
                {
                    bail!("不能写入合并单元格子区域：{reference}");
                }
            }
        }
    }
    let mut edits = vec![];
    let existing: BTreeMap<_, _> = children(data, "row")
        .map(|n| Ok((n.attribute("r").context("行号缺失")?.parse::<u32>()?, n)))
        .collect::<Result<_>>()?;
    let mut per_row = BTreeMap::<u32, Vec<(u32, String, Option<&Cell>)>>::new();
    for ((r, c), (a, v)) in all {
        per_row.entry(r).or_default().push((c, a, v));
    }
    for (r, values) in per_row {
        if let Some(row) = existing.get(&r) {
            let cells: BTreeMap<_, _> = children(*row, "c")
                .map(|n| Ok((coord(n.attribute("r").context("单元格地址缺失")?)?.1, n)))
                .collect::<Result<_>>()?;
            let mut insertions = BTreeMap::<usize, String>::new();
            for (c, address, value) in values {
                let old = cells.get(&c).copied();
                let style = update.formats.get(&address).map(|fmt| {
                    let original = old
                        .and_then(|n| n.attribute("s"))
                        .unwrap_or("0")
                        .parse::<usize>()
                        .unwrap_or(0);
                    styles[&(original, *fmt)]
                });
                let result = cell(old, &address, value, style, source)?;
                if let Some(n) = old {
                    edits.push((n.range(), result));
                } else {
                    let at = cells
                        .range(c + 1..)
                        .next()
                        .map(|(_, n)| n.range().start)
                        .unwrap_or_else(|| row.range().end - 6);
                    insertions.entry(at).or_default().push_str(&result);
                }
            }
            // Self-closing empty rows have no closing </row> to insert before.
            if cells.is_empty() && source[row.range()].trim_end().ends_with("/>") {
                let mut body = source[row.range()].trim_end_matches("/>").to_string();
                body.push('>');
                for v in insertions.values() {
                    body.push_str(v);
                }
                body.push_str("</row>");
                edits.push((row.range(), body));
            } else {
                edits.extend(insertions.into_iter().map(|(at, s)| (at..at, s)));
            }
        } else {
            let mut body = format!("<row r=\"{r}\">");
            for (_, address, value) in values {
                let style = update.formats.get(&address).map(|f| styles[&(0, *f)]);
                body.push_str(&cell(None, &address, value, style, source)?);
            }
            body.push_str("</row>");
            let at = existing
                .range(r + 1..)
                .next()
                .map(|(_, n)| n.range().start)
                .unwrap_or(data.range().end - 12);
            edits.push((at..at, body));
        }
    }
    replace(source, edits)
}

pub fn write(template: &Path, output: &Path, updates: &Updates) -> Result<()> {
    ensure!(
        template.canonicalize()?
            != output
                .canonicalize()
                .unwrap_or_else(|_| output.to_path_buf()),
        "请导出到新文件，不能覆盖原模板"
    );
    ensure!(
        template
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("xlsx")),
        "模板必须是 .xlsx 格式"
    );
    let mut archive = ZipArchive::new(File::open(template)?)?;
    let mut parts = BTreeMap::<String, Vec<u8>>::new();
    for i in 0..archive.len() {
        let mut file = archive.by_index(i)?;
        let mut bytes = vec![];
        file.read_to_end(&mut bytes)?;
        parts.insert(file.name().into(), bytes);
    }
    let part = |name: &str| -> Result<&str> {
        Ok(std::str::from_utf8(
            parts
                .get(name)
                .with_context(|| format!("缺少工作簿部件：{name}"))?,
        )?)
    };
    let workbook = part("xl/workbook.xml")?;
    let rels = Document::parse(part("xl/_rels/workbook.xml.rels")?)?;
    let relationships: BTreeMap<_, _> = rels
        .descendants()
        .filter(|n| n.has_tag_name("Relationship"))
        .filter_map(|n| Some((n.attribute("Id")?, n.attribute("Target")?)))
        .collect();
    let doc = Document::parse(workbook)?;
    let sheets: BTreeMap<_, _> = doc
        .descendants()
        .filter(|n| n.has_tag_name("sheet"))
        .filter_map(|n| {
            Some((
                n.attribute("name")?,
                n.attributes().find(|a| a.name() == "id")?.value(),
            ))
        })
        .map(|(name, id)| {
            let target = relationships.get(id).context("缺少工作表关系")?;
            let path = if target.starts_with('/') {
                target.trim_start_matches('/').into()
            } else {
                format!("xl/{target}")
            };
            Ok((name, path))
        })
        .collect::<Result<_>>()?;
    let styles_src = part("xl/styles.xml")?;
    let style_doc = Document::parse(styles_src)?;
    let xfs = style_doc
        .descendants()
        .find(|n| n.has_tag_name("cellXfs"))
        .context("缺少 cellXfs")?;
    let originals: Vec<_> = children(xfs, "xf").collect();
    let mut style_map = BTreeMap::new();
    let mut added = String::new();
    for (sheet, update) in updates {
        let src = part(
            sheets
                .get(sheet.as_str())
                .with_context(|| format!("模板缺少工作表：{sheet}"))?,
        )?;
        let d = Document::parse(src)?;
        for (address, fmt) in &update.formats {
            let old = d
                .descendants()
                .find(|n| n.has_tag_name("c") && n.attribute("r") == Some(address))
                .and_then(|n| n.attribute("s"))
                .unwrap_or("0")
                .parse::<usize>()?;
            if !style_map.contains_key(&(old, *fmt)) {
                let original = originals.get(old).context("模板样式索引无效")?;
                let value = set_attr(&styles_src[original.range()], "numFmtId", &fmt.to_string())?;
                let value = set_attr(&value, "applyNumberFormat", "1")?;
                style_map.insert((old, *fmt), originals.len() + style_map.len());
                added.push_str(&value);
            }
        }
    }
    let mut replacements = BTreeMap::<String, String>::new();
    if !added.is_empty() {
        let mut section = styles_src[xfs.range()].to_string();
        let at = section.rfind("</").context("cellXfs 无效")?;
        section.insert_str(at, &added);
        section = set_attr(
            &section,
            "count",
            &(originals.len() + style_map.len()).to_string(),
        )?;
        replacements.insert(
            "xl/styles.xml".into(),
            replace(styles_src, vec![(xfs.range(), section)])?,
        );
    }
    for (sheet, update) in updates {
        let path = sheets[sheet.as_str()].clone();
        replacements.insert(path.clone(), sheet_xml(part(&path)?, update, &style_map)?);
    }
    if let Some(calc) = doc.descendants().find(|n| n.has_tag_name("calcPr")) {
        let mut value = set_attr(&workbook[calc.range()], "fullCalcOnLoad", "1")?;
        value = set_attr(&value, "forceFullCalc", "1")?;
        value = set_attr(&value, "calcMode", "auto")?;
        replacements.insert(
            "xl/workbook.xml".into(),
            replace(workbook, vec![(calc.range(), value)])?,
        );
    } else {
        let at = workbook.rfind("</").context("workbook 无效")?;
        replacements.insert(
            "xl/workbook.xml".into(),
            replace(
                workbook,
                vec![(
                    at..at,
                    "<calcPr fullCalcOnLoad=\"1\" forceFullCalc=\"1\" calcMode=\"auto\"/>".into(),
                )],
            )?,
        );
    }
    // Everything has validated before a destination is created. Commit the complete zip atomically.
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    {
        let mut writer = ZipWriter::new(temp.as_file_mut());
        for i in 0..archive.len() {
            let entry = archive.by_index(i)?;
            if let Some(value) = replacements.get(entry.name()) {
                writer.start_file(
                    entry.name(),
                    SimpleFileOptions::default().compression_method(entry.compression()),
                )?;
                writer.write_all(value.as_bytes())?;
            } else {
                writer.raw_copy_file(entry)?;
            }
        }
        writer.finish()?;
    }
    temp.as_file_mut().sync_all()?;
    temp.persist(output)
        .map_err(|e| e.error)
        .with_context(|| format!("无法保存 {}，请检查文件是否被 Excel 占用", output.display()))?;
    Ok(())
}

pub fn validate_simple_template(path: &Path) -> Result<()> {
    use calamine::Reader;
    let mut book = calamine::open_workbook_auto(path)?;
    let a = book
        .worksheet_range("Sheet1")
        .context("请选择 T-CD 简表模板")?;
    let b = book
        .worksheet_range("Sheet2")
        .context("请选择 T-CD 简表模板")?;
    let value = |range: &calamine::Range<calamine::Data>, r, c| {
        range
            .get_value((r, c))
            .map(ToString::to_string)
            .unwrap_or_default()
    };
    ensure!(
        value(&a, 0, 0).contains("数据简表")
            && value(&a, 12, 0) == "无卡次数"
            && value(&b, 3, 0) == "油品"
            && value(&b, 9, 0) == "充值明细",
        "模板内容不是支持的 T-CD 简表"
    );
    Ok(())
}
