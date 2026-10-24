use anyhow::{Context, Result, bail, ensure};
use calamine::{Reader, open_workbook_auto};
use chrono::NaiveDateTime;
use regex::Regex;
use rust_decimal::Decimal;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    str::FromStr,
};

pub type Row = BTreeMap<String, String>;
#[derive(Debug)]
pub struct Table {
    pub rows: Vec<Row>,
    pub period: Vec<NaiveDateTime>,
    pub stations: BTreeSet<String>,
}
/// Ignore presentation whitespace in labels, never in numeric values.
pub fn label(value: &str) -> String {
    value
        .chars()
        .filter(|c| !c.is_whitespace() && *c != '\u{feff}')
        .collect()
}
pub fn number(value: &str) -> Result<Decimal> {
    let value = value.trim();
    let grouped = value.replace('，', ",");
    let cleaned = if grouped.contains(',') {
        ensure!(
            Regex::new(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")?.is_match(&grouped),
            "无效数值：{value:?}"
        );
        grouped.replace(',', "")
    } else {
        grouped
    };
    Decimal::from_str(&cleaned)
        .or_else(|_| Decimal::from_scientific(&cleaned))
        .with_context(|| format!("无效数值：{value:?}"))
}
pub fn num(row: &Row, name: &str) -> Result<Decimal> {
    number(row.get(name).map(String::as_str).unwrap_or("")).with_context(|| name.to_owned())
}
pub fn text<'a>(row: &'a Row, name: &str) -> &'a str {
    row.get(name).map(String::as_str).unwrap_or("")
}
pub fn rows(path: &Path) -> Result<Vec<Vec<String>>> {
    if path
        .extension()
        .is_some_and(|s| s.eq_ignore_ascii_case("csv"))
    {
        let mut reader = csv::ReaderBuilder::new()
            .has_headers(false)
            .flexible(true)
            .from_path(path)?;
        return reader
            .records()
            .map(|r| Ok(r?.iter().map(|s| s.trim().to_owned()).collect()))
            .collect();
    }
    let mut book =
        open_workbook_auto(path).with_context(|| format!("无法读取 {}", path.display()))?;
    let range = book.worksheet_range_at(0).context("工作簿没有工作表")??;
    Ok(range
        .rows()
        .map(|r| r.iter().map(|v| v.to_string().trim().to_owned()).collect())
        .collect())
}
pub fn read(path: &Path, required: &[&str], numeric: &[&str], discount: bool) -> Result<Table> {
    let all = rows(path)?;
    let header = all
        .iter()
        .position(|row| required.iter().all(|k| row.iter().any(|v| label(v) == *k)))
        .with_context(|| format!("{} 找不到表头：{}", path.display(), required.join("、")))?;
    let labels: Vec<_> = all[header].iter().map(|v| label(v)).collect();
    for key in required
        .iter()
        .chain(numeric)
        .chain([&"站号", &"加油完成时间"])
    {
        if !required.contains(key) && !labels.iter().any(|v| v == key) {
            continue;
        }
        if labels.iter().filter(|v| v == key).count() != 1 {
            bail!("表头字段重复：{key}")
        }
    }
    let footer = Regex::new(r"^(合计|汇总|总计|小计|记录总数|次数)($|[（(:：])")?;
    let times = Regex::new(r"\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}:\d{2}")?;
    let heading = all[..header]
        .iter()
        .flatten()
        .cloned()
        .collect::<Vec<_>>()
        .join(" ");
    let period = times
        .find_iter(&heading)
        .map(|m| NaiveDateTime::parse_from_str(m.as_str(), "%Y-%m-%d %H:%M:%S"))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let mut table = Table {
        rows: vec![],
        period,
        stations: BTreeSet::new(),
    };
    for (i, values) in all.iter().enumerate().skip(header + 1) {
        if values.iter().all(String::is_empty) || values.iter().take(4).any(|v| footer.is_match(v))
        {
            continue;
        }
        let mut row: Row = labels
            .iter()
            .enumerate()
            .filter(|(_, k)| !k.is_empty())
            .map(|(j, k)| (k.clone(), values.get(j).cloned().unwrap_or_default()))
            .collect();
        if let Some(fuel) = row.get_mut("油品") {
            let normalized = label(fuel).replace('＃', "#");
            if crate::report::FUELS.contains(&normalized.as_str()) {
                *fuel = normalized;
            }
        }
        if discount && (text(&row, "油品").is_empty() || number(text(&row, "油品")).is_ok()) {
            continue;
        }
        for key in numeric {
            num(&row, key).with_context(|| format!("{} 第 {} 行", path.display(), i + 1))?;
        }
        if let Ok(n) = num(&row, "站号") {
            table.stations.insert(n.normalize().to_string());
        }
        table.rows.push(row);
    }
    Ok(table)
}
pub fn consistent(tables: &[&Table]) -> Result<()> {
    let periods: BTreeSet<_> = tables
        .iter()
        .filter(|t| t.period.len() == 2)
        .map(|t| &t.period)
        .collect();
    if periods.len() > 1 {
        bail!("源表导出时段不一致")
    }
    let stations: BTreeSet<_> = tables
        .iter()
        .filter(|t| !t.stations.is_empty())
        .map(|t| &t.stations)
        .collect();
    if stations.len() > 1 {
        bail!("源表站号不一致")
    }
    Ok(())
}
