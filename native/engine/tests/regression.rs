use calamine::Reader;
use financial_engine::{Cell, Request, SheetUpdate, Updates, report, source, workbook};
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Read, Write},
    path::{Path, PathBuf},
};
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};
fn source_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.context/attachments")
}
fn request(root: &Path) -> Request {
    Request {
        sources: BTreeMap::from([
            ("油品时间统计".into(), root.join("stats.csv")),
            ("加油明细".into(), root.join("details.csv")),
            ("充值明细".into(), root.join("recharge.csv")),
        ]),
        day: 20,
        divisor: "3".into(),
        count_divisor: "3".into(),
        closing_balance: String::new(),
    }
}
fn fixture(root: &Path) {
    std::fs::write(root.join("stats.csv"),"机号,油品,加油升,加油元,次数\n3,0#柴油,30,240,1\n9,92#汽油,30,270,1\n11,95#汽油,30,300,1\n汇总,,90,810,3\n").unwrap();
    std::fs::write(root.join("details.csv"),"油品,单价,升数,油机金额,结算金额,优惠金额,收款方式\n0#柴油,8,30,240,234,6,充值卡收款 \n92#汽油,9,30,270,258,9,电子卡收款 \n95#汽油,10,30,300,300,0,现金收款\n").unwrap();
    std::fs::write(root.join("recharge.csv"),"原余额,充值金额,充值赠送,付款方式\n100,300,30,现金收款 \n100,600,0,微信收款 \n100,600,0,支付宝收款\n0,0,0,\n次数,1500,30,\n").unwrap();
}
fn value(report: &financial_engine::Report, cell: &str) -> String {
    match &report.updates["Sheet1"].cells[cell] {
        Cell::Number(v) => v.clone(),
        other => panic!("unexpected {other:?}"),
    }
}
#[test]
fn consumption_recharge_and_count_rules() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let r = report::simple(&request(dir.path())).unwrap();
    for (cell, expected) in [
        ("D9", "510"),
        ("B9", "1.33"),
        ("B12", "400"),
        ("D11", "164"),
        ("D12", "86"),
        ("D13", "100"),
    ] {
        assert_eq!(value(&r, cell), expected, "{cell}");
    }
    assert!(matches!(r.updates["Sheet1"].cells["B8"], Cell::Blank));
    assert!(!r.updates["Sheet1"].cells.contains_key("B10"));
}
#[test]
fn negative_recharge_gifts_and_blank_cancellation() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    std::fs::write(dir.path().join("recharge.csv"),"原余额,充值金额,充值赠送,付款方式\n100,-300,30,现金收款\n100,600,0,微信收款\n100,999,0,\n0,300,30,支付宝收款\n").unwrap();
    let r = report::simple(&request(dir.path())).unwrap();
    assert_eq!(value(&r, "D9"), "110");
    assert_eq!(value(&r, "D8"), "110");
    assert_eq!(value(&r, "B9"), "1.33");
}
#[test]
fn reject_invalid_sources_and_divisors() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let mut req = request(dir.path());
    req.divisor = "0".into();
    assert!(report::simple(&req).is_err());
    req.divisor = "3".into();
    req.closing_balance = "NaN".into();
    assert!(report::simple(&req).is_err());
    req.closing_balance = "0".into();
    assert_eq!(value(&report::simple(&req).unwrap(), "G7"), "0");
    let p = dir.path().join("details.csv");
    let content = std::fs::read_to_string(&p).unwrap();
    std::fs::write(&p, content.replace("240,234", "241,234")).unwrap();
    assert!(format!("{:#}", report::simple(&req).unwrap_err()).contains("油机金额不一致"));
}
#[test]
fn reject_duplicate_headers() {
    let dir = tempfile::tempdir().unwrap();
    let p = dir.path().join("a.csv");
    std::fs::write(&p, "油品,优惠,优惠\n0#柴油,1,2\n").unwrap();
    assert!(source::read(&p, &["油品", "优惠"], &["优惠"], true).is_err());
}
#[test]
fn verified_oct20_values_and_output_preservation() {
    let base = source_dir();
    let template = base.join("0LPzc8/T-CD简20(1).xlsx");
    if !template.exists() {
        eprintln!(
            "private sample absent; run scripts/verify-native.py in the attachment workspace"
        );
        return;
    }
    let mut req = request(&base);
    req.sources = BTreeMap::from([
        ("油品时间统计".into(), base.join("H08NC1/1(5).xlsx")),
        ("加油明细".into(), base.join("cCDPeT/3(5).xlsx")),
        ("充值明细".into(), base.join("mKlowY/4(5).xlsx")),
    ]);
    let result = report::simple(&req).unwrap();
    let mut book = calamine::open_workbook_auto(&template).unwrap();
    let sample = book.worksheet_range("Sheet1").unwrap();
    let addresses = [
        "B3", "D3", "E3", "B4", "D4", "E4", "B5", "D5", "E5", "B9", "D9", "D11", "B12", "D12",
        "B13",
    ];
    for address in addresses {
        let col = address.as_bytes()[0] - b'A';
        let row: usize = address[1..].parse::<usize>().unwrap() - 1;
        let sample = sample
            .get_value((row as u32, col as u32))
            .unwrap()
            .to_string();
        assert_eq!(
            source::number(&value(&result, address)).unwrap(),
            source::number(&sample).unwrap(),
            "{address}"
        );
    }
    assert_eq!(value(&result, "D13"), "1586.33");
    assert_eq!(sample.get_value((12, 3)).unwrap().to_string(), "1550.99");
    let out = tempfile::tempdir().unwrap();
    let path = out.path().join("简表.xlsx");
    workbook::write(&template, &path, &result.updates).unwrap();
    let mut output = calamine::open_workbook_auto(&path).unwrap();
    let sheet = output.worksheet_range("Sheet1").unwrap();
    assert_eq!(sheet.get_value((8, 3)).unwrap().to_string(), "12715.83");
    preserved(
        &template,
        &path,
        &[
            "xl/worksheets/sheet1.xml",
            "xl/worksheets/sheet2.xml",
            "xl/styles.xml",
            "xl/workbook.xml",
        ],
    );
    let again = out.path().join("again.xlsx");
    workbook::write(&path, &again, &result.updates).unwrap();
    let mut second = calamine::open_workbook_auto(&again).unwrap();
    assert_eq!(second.worksheet_range("Sheet1").unwrap(), sheet);
}
fn preserved(a: &Path, b: &Path, changed: &[&str]) {
    let mut a = ZipArchive::new(File::open(a).unwrap()).unwrap();
    let mut b = ZipArchive::new(File::open(b).unwrap()).unwrap();
    assert_eq!(a.len(), b.len());
    for i in 0..a.len() {
        let mut original = a.by_index(i).unwrap();
        let name = original.name().to_string();
        if changed.contains(&name.as_str()) {
            continue;
        }
        let mut one = vec![];
        original.read_to_end(&mut one).unwrap();
        let mut two = vec![];
        b.by_name(&name).unwrap().read_to_end(&mut two).unwrap();
        assert_eq!(one, two, "{name}");
    }
}
fn minimal(path: &Path) {
    let mut zip = ZipWriter::new(File::create(path).unwrap());
    let parts = [
        (
            "xl/workbook.xml",
            r#"<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>"#,
        ),
        (
            "xl/_rels/workbook.xml.rels",
            r#"<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>"#,
        ),
        (
            "xl/styles.xml",
            r#"<styleSheet><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs></styleSheet>"#,
        ),
        (
            "xl/worksheets/sheet1.xml",
            r#"<worksheet><sheetData><row r="1"><c r="A1" s="0"><v>7</v></c></row><row r="2"/></sheetData><mergeCells><mergeCell ref="A1:B1"/></mergeCells></worksheet>"#,
        ),
        (
            "xl/media/image1.png",
            "this opaque fixture must survive byte-for-byte",
        ),
        ("xl/drawings/drawing1.xml", "<drawing>untouched</drawing>"),
    ];
    for (name, value) in parts {
        zip.start_file(name, SimpleFileOptions::default()).unwrap();
        zip.write_all(value.as_bytes()).unwrap();
    }
    zip.finish().unwrap();
}
#[test]
fn patch_preserves_media_and_rejects_merged_children_atomically() {
    let dir = tempfile::tempdir().unwrap();
    let template = dir.path().join("template.xlsx");
    minimal(&template);
    let out = dir.path().join("out.xlsx");
    std::fs::write(&out, "existing destination").unwrap();
    let mut sheet = SheetUpdate::default();
    sheet.cells.insert("B1".into(), Cell::Number("1".into()));
    let mut updates = Updates::from([("Sheet1".into(), sheet)]);
    assert!(workbook::write(&template, &out, &updates).is_err());
    assert_eq!(
        std::fs::read_to_string(&out).unwrap(),
        "existing destination"
    );
    updates.get_mut("Sheet1").unwrap().cells = BTreeMap::from([
        ("A2".into(), Cell::Text("<& test".into())),
        ("D3".into(), Cell::Number("3".into())),
    ]);
    workbook::write(&template, &out, &updates).unwrap();
    preserved(
        &template,
        &out,
        &["xl/worksheets/sheet1.xml", "xl/workbook.xml"],
    );
    let mut z = ZipArchive::new(File::open(out).unwrap()).unwrap();
    let mut s = String::new();
    z.by_name("xl/worksheets/sheet1.xml")
        .unwrap()
        .read_to_string(&mut s)
        .unwrap();
    roxmltree::Document::parse(&s).unwrap();
    assert!(s.contains("&lt;&amp; test"));
    assert!(workbook::write(&template, &template, &updates).is_err());
}
#[test]
fn reads_real_grouped_xls() {
    let p = source_dir().join("ZRUN60/2(1).xls");
    if !p.exists() {
        return;
    }
    let rows = source::read(&p, &["油品", "优惠"], &["优惠"], true).unwrap();
    assert!(!rows.rows.is_empty());
    assert!(
        rows.rows
            .iter()
            .all(|r| report::FUELS.contains(&source::text(r, "油品")))
    );
}

#[test]
fn recognition_requires_numbers_instead_of_silent_zero() {
    use financial_engine::receipts;
    assert_eq!(
        receipts::parse(&serde_json::json!("25,378.75 元"))
            .unwrap()
            .to_string(),
        "25378.75"
    );
    assert_eq!(
        receipts::parse(&serde_json::json!("-300元"))
            .unwrap()
            .to_string(),
        "-300"
    );
    assert!(receipts::parse(&serde_json::Value::Null).is_err());
    assert!(receipts::parse(&serde_json::json!("未知")).is_err());
    assert!(receipts::parse(&serde_json::json!("100元/200元")).is_err());
}

#[test]
fn real_embedded_screenshots_survive_a_template_edit() {
    for relative in ["a8JA1z/1(3).xlsx", "But3s4/4(3).xlsx"] {
        let path = source_dir().join(relative);
        if !path.exists() {
            continue;
        }
        let book = calamine::open_workbook_auto(&path).unwrap();
        let name = book.sheet_names()[0].clone();
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("图片保真.xlsx");
        let update = SheetUpdate {
            cells: BTreeMap::from([("A1".into(), Cell::Text("保真校验".into()))]),
            formats: BTreeMap::new(),
        };
        workbook::write(&path, &dest, &Updates::from([(name, update)])).unwrap();
        preserved(
            &path,
            &dest,
            &["xl/worksheets/sheet1.xml", "xl/workbook.xml"],
        );
        let mut zip = ZipArchive::new(File::open(dest).unwrap()).unwrap();
        assert!((0..zip.len()).any(|i| zip.by_index(i).unwrap().name().starts_with("xl/media/")));
    }
}

#[test]
fn multiple_receipts_round_each_image_then_accumulate_all_cells() {
    let dir = tempfile::tempdir().unwrap();
    let template = dir.path().join("daily.xlsx");
    let mut zip = ZipWriter::new(File::create(&template).unwrap());
    for (name, data) in [
        (
            "_rels/.rels",
            r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"#,
        ),
        (
            "[Content_Types].xml",
            r#"<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>"#,
        ),
        (
            "xl/workbook.xml",
            r#"<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="油品优惠明细 2" sheetId="1" r:id="rId1"/></sheets></workbook>"#,
        ),
        (
            "xl/_rels/workbook.xml.rels",
            r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>"#,
        ),
        (
            "xl/worksheets/sheet1.xml",
            r#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="2"><c r="B2"><v>20</v></c></row></sheetData></worksheet>"#,
        ),
    ] {
        zip.start_file(name, SimpleFileOptions::default()).unwrap();
        zip.write_all(data.as_bytes()).unwrap();
    }
    zip.finish().unwrap();
    let mut output = financial_engine::Report {
        updates: Default::default(),
        notes: vec![],
    };
    let data = serde_json::json!({"柴油统计":1,"油站折扣":1,"油站直降":0,"服务费":1,"结算金额":1});
    let recognized = vec![
        ("货车帮".into(), data.clone()),
        ("货车帮".into(), data),
        (
            "滴滴加油".into(),
            serde_json::json!({"油品应收金额":30,"油品预收金额":33,"油品优惠合计":3,"油品数量":9}),
        ),
    ];
    financial_engine::receipts::apply_many(
        &mut output,
        &template,
        20,
        source::number("8.23").unwrap(),
        &recognized,
    )
    .unwrap();
    let number = |sheet: &str, address: &str| match &output.updates[sheet].cells[address] {
        Cell::Number(n) => n.clone(),
        _ => panic!("expected number"),
    };
    assert_eq!(number("调价前", "C90"), "0.66"); // round(1/3) + round(1/3), not round(2/3)
    assert_eq!(number("调价前", "E81"), "1.66"); // adds fees from both categories too
    assert_eq!(number("油品优惠明细 2", "AA2"), "0.66");
    assert_eq!(number("油品优惠明细 2", "AB2"), "0.66");
}

#[test]
fn daily_preserves_cash_allocation_formula_but_updates_plain_values() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let discounts = dir.path().join("discounts.csv");
    std::fs::write(&discounts, "油品,优惠\n0#柴油,6\n92#汽油,9\n").unwrap();
    let mut req = request(dir.path());
    req.sources.insert("油品优惠".into(), discounts);

    for (cash_xml, preserve) in [
        ("<f>110-C72</f><v>85</v>", true),
        ("<v>999</v>", false),
        ("<v>0</v>", false),
        ("", false),
    ] {
        let template = dir.path().join("daily.xlsx");
        let mut zip = ZipWriter::new(File::create(&template).unwrap());
        let daily_xml = format!(
            r#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
            <row r="3"><c r="A3" t="inlineStr"><is><t>A</t></is></c><c r="B3"><v>3</v></c></row>
            <row r="4"><c r="A4" t="inlineStr"><is><t>B</t></is></c><c r="B4"><v>9</v></c></row>
            <row r="5"><c r="A5" t="inlineStr"><is><t>C</t></is></c><c r="B5"><v>11</v></c></row>
            <row r="68"><c r="C68">{cash_xml}</c><c r="E68"><f>C68+C72+C73</f><v>510</v></c></row>
            <row r="72"><c r="C72"><v>25</v></c></row>
            <row r="73"><c r="C73"><v>999</v></c></row>
            </sheetData></worksheet>"#
        );
        for (name, data) in [
            (
                "_rels/.rels",
                r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"#,
            ),
            (
                "[Content_Types].xml",
                r#"<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>"#,
            ),
            (
                "xl/workbook.xml",
                r#"<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="调价前" sheetId="1" r:id="rId1"/><sheet name="油品优惠明细 2" sheetId="2" r:id="rId2"/></sheets></workbook>"#,
            ),
            (
                "xl/_rels/workbook.xml.rels",
                r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>"#,
            ),
            (
                "xl/styles.xml",
                r#"<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs></styleSheet>"#,
            ),
            ("xl/worksheets/sheet1.xml", daily_xml.as_str()),
            (
                "xl/worksheets/sheet2.xml",
                r#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="2"><c r="B2"><v>20</v></c></row></sheetData></worksheet>"#,
            ),
        ] {
            zip.start_file(name, SimpleFileOptions::default()).unwrap();
            zip.write_all(data.as_bytes()).unwrap();
        }
        zip.finish().unwrap();

        let report = report::daily(&req, &template).unwrap();
        assert_eq!(
            report.updates["调价前"].cells.contains_key("C68"),
            !preserve
        );
        let output = dir.path().join("output.xlsx");
        workbook::write(&template, &output, &report.updates).unwrap();
        let mut book = calamine::open_workbook_auto(&output).unwrap();
        let values = book.worksheet_range("调价前").unwrap();
        let formulas = book.worksheet_formula("调价前").unwrap();
        assert_eq!(values.get_value((71, 2)).unwrap().to_string(), "25");
        assert_eq!(values.get_value((72, 2)).unwrap().to_string(), "400");
        assert_eq!(formulas.get_value((67, 4)).unwrap(), "C68+C72+C73");
        if preserve {
            assert_eq!(formulas.get_value((67, 2)).unwrap(), "110-C72");
        } else {
            assert_eq!(values.get_value((67, 2)).unwrap().to_string(), "110");
        }
    }
}
