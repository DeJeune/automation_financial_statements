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
    std::fs::write(root.join("details.csv"),"油品,单价,升数,油机金额,结算金额,优惠金额,收款方式,IC卡余额,实收金额\n0#柴油,8,30,240,234,6,充值卡收款 ,0,230\n92#汽油,9,30,270,258,9,电子卡收款 ,0,250\n95#汽油,10,30,300,300,0,现金收款,0,290\n").unwrap();
    std::fs::write(root.join("recharge.csv"),"原余额,充值金额,充值赠送,付款方式\n100,300,30,现金收款 \n100,600,0,微信收款 \n100,600,0,支付宝收款\n0,0,0,\n次数,1500,30,\n").unwrap();
}
fn value(report: &financial_engine::Report, cell: &str) -> String {
    match &report.updates["Sheet1"].cells[cell] {
        Cell::Number(v) => v.clone(),
        other => panic!("unexpected {other:?}"),
    }
}
fn price_change_fixture(root: &Path) -> Request {
    fixture(root);
    std::fs::write(root.join("stats.csv"), "油品时间统计\n时间：2026-10-20 07:00:00------2026-10-20 12:00:00\n站号,机号,油品,加油升,加油元,次数\n14,3,0#柴油,30.01,240.08,1\n14,9,92#汽油,3.01,27.09,1\n14,11,95#汽油,6.01,60.10,1\n合计,,,39.03,327.27,3\n").unwrap();
    std::fs::write(root.join("after.csv"), "油品时间统计\n时间：2026-10-20 12:00:00------2026-10-21 07:00:00\n站号,机号,油品,加油升,加油元,次数\n14,3,0#柴油,30.01,270.09,1\n14,9,92#汽油,3.01,30.10,1\n14,11,95#汽油,6.01,66.11,1\n合计,,,39.03,366.30,3\n").unwrap();
    std::fs::write(root.join("details.csv"), "加油明细\n时间：2026-10-20 07:00:00------2026-10-21 07:00:00\n油品,单价,升数,油机金额,结算金额,优惠金额,收款方式,IC卡余额,加油完成时间,实收金额\n0#柴油,8,30.01,240.08,240.08,0,现金收款,0,2026-10-20 11:00:00,240.08\n0#柴油,9,30.01,270.09,270.09,0,现金收款,0,2026-10-20 12:00:00,270.09\n92#汽油,9,3.01,27.09,27.09,0,现金收款,0,2026-10-20 11:00:00,27.09\n92#汽油,10,3.01,30.10,30.10,0,现金收款,0,2026-10-20 12:00:00,30.10\n95#汽油,10,6.01,60.10,60.10,0,现金收款,0,2026-10-20 11:00:00,60.10\n95#汽油,11,6.01,66.11,66.11,0,现金收款,0,2026-10-20 12:00:00,66.11\n").unwrap();
    let mut req = request(root);
    req.sources
        .insert("油品时间统计(调价后)".into(), root.join("after.csv"));
    req
}

#[test]
fn price_change_combines_litres_amounts_counts_and_periods() {
    let dir = tempfile::tempdir().unwrap();
    let req = price_change_fixture(dir.path());
    let result = report::simple(&req).unwrap();
    for (cell, expected) in [
        ("B3", "20"),
        ("D3", "170"),
        ("E3", "1"),
        ("B4", "2"),
        ("D4", "19"),
        ("E4", "1"),
        ("B5", "4"),
        ("D5", "42"),
        ("E5", "1"),
    ] {
        assert_eq!(value(&result, cell), expected, "{cell}");
    }
    let template = Path::new(env!("CARGO_MANIFEST_DIR")).join("../app/fixtures/simple.xlsx");
    let report = report::simple_for_template(&req, &template).unwrap();
    let output = dir.path().join("simple.xlsx");
    workbook::write(&template, &output, &report.updates).unwrap();
    let mut book = calamine::open_workbook_auto(output).unwrap();
    let range = book.worksheet_range_at(0).unwrap().unwrap();
    assert_eq!(range.get_value((2, 1)).unwrap().to_string(), "20");
    assert_eq!(range.get_value((2, 3)).unwrap().to_string(), "170");
    assert_eq!(range.get_value((2, 4)).unwrap().to_string(), "1");
}

#[test]
fn after_statistics_are_validated_instead_of_ignored() {
    let dir = tempfile::tempdir().unwrap();
    let req = price_change_fixture(dir.path());
    let path = dir.path().join("after.csv");
    let original = std::fs::read_to_string(&path).unwrap();
    for (from, to, message) in [
        ("30.01,270.09,1", "31.01,270.09,1", "升数不一致"),
        ("30.01,270.09,1", "30.01,271.09,1", "油机金额不一致"),
        ("30.01,270.09,1", "30.01,270.09,2", "次数不一致"),
        ("\n14,", "\n15,", "站号不一致"),
        ("2026-10-21 07:00:00", "2026-10-21 06:00:00", "时段不一致"),
        ("95#汽油", "98#汽油", "未支持的油品"),
        ("加油元", "缺失金额列", "找不到表头"),
    ] {
        std::fs::write(&path, original.replace(from, to)).unwrap();
        let error = report::simple(&req).unwrap_err();
        assert!(format!("{error:#}").contains(message), "{error:#}");
    }
}

fn daily_template_with_after(root: &Path) -> PathBuf {
    let template = root.join("daily.xlsx");
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR")).join("../app/fixtures/daily.xlsx");
    let mut input = ZipArchive::new(File::open(fixture).unwrap()).unwrap();
    let mut output = ZipWriter::new(File::create(&template).unwrap());
    for i in 0..input.len() {
        let mut entry = input.by_index(i).unwrap();
        let name = entry.name().to_owned();
        let mut bytes = vec![];
        entry.read_to_end(&mut bytes).unwrap();
        if [
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "[Content_Types].xml",
        ]
        .contains(&name.as_str())
        {
            let xml = String::from_utf8(bytes).unwrap();
            bytes = match name.as_str() {
                "xl/workbook.xml" => xml.replace("</sheets>", r#"<sheet name="调价后" sheetId="3" r:id="rId3"/></sheets>"#),
                "xl/_rels/workbook.xml.rels" => xml.replace("</Relationships>", r#"<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/></Relationships>"#),
                _ => xml.replace("</Types>", r#"<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>"#),
            }.into_bytes();
        }
        output
            .start_file(name, SimpleFileOptions::default())
            .unwrap();
        output.write_all(&bytes).unwrap();
    }
    output
        .start_file("xl/worksheets/sheet3.xml", SimpleFileOptions::default())
        .unwrap();
    output.write_all(br#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
        <row r="3"><c r="A3" t="inlineStr"><is><t>A</t></is></c><c r="B3"><v>3</v></c><c r="D3"><v>999</v></c><c r="G3"><v>7</v></c><c r="H3"><f>D3*G3</f><v>6993</v></c></row>
        <row r="4"><c r="A4" t="inlineStr"><is><t>B</t></is></c><c r="B4"><v>9</v></c><c r="D4"><v>999</v></c><c r="G4"><v>7</v></c><c r="H4"><f>D4*G4</f><v>6993</v></c></row>
        <row r="5"><c r="A5" t="inlineStr"><is><t>C</t></is></c><c r="B5"><v>11</v></c><c r="D5"><v>999</v></c><c r="G5"><v>7</v></c><c r="H5"><f>D5*G5</f><v>6993</v></c></row>
        </sheetData></worksheet>"#).unwrap();
    output.finish().unwrap();
    template
}

#[test]
fn same_price_splits_keep_original_algorithm_and_daily_template_prices_cannot_change_it() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    std::fs::write(
        dir.path().join("stats.csv"),
        "机号,油品,加油升,加油元,次数\n9,92#汽油,123.65,1075.73,1\n",
    )
    .unwrap();
    std::fs::write(
        dir.path().join("after.csv"),
        "机号,油品,加油升,加油元,次数\n9,92#汽油,315.02,2739.85,1\n",
    )
    .unwrap();
    std::fs::write(dir.path().join("details.csv"), "油品,单价,升数,油机金额,结算金额,优惠金额,收款方式,IC卡余额,实收金额\n92#汽油,8.7,123.65,1075.73,1075.73,0,现金收款,0,1075.73\n92#汽油,8.7,315.02,2739.85,2739.85,0,现金收款,0,2739.85\n").unwrap();
    let mut req = request(dir.path());
    req.sources
        .insert("油品时间统计(调价后)".into(), dir.path().join("after.csv"));
    let simple = report::simple(&req).unwrap();
    assert_eq!(value(&simple, "B4"), "146.22");
    assert_eq!(value(&simple, "D4"), "1272.11");
    assert_eq!(value(&simple, "E4"), "1");
    std::fs::write(dir.path().join("discounts.csv"), "油品,优惠\n92#汽油,0\n").unwrap();
    req.sources
        .insert("油品优惠".into(), dir.path().join("discounts.csv"));
    let template = daily_template_with_after(dir.path());
    let daily = report::daily(&req, &template).unwrap();
    for (sheet, cell, expected) in [
        ("调价前", "D4", "146.22"),
        ("调价前", "G4", "8.7"),
        ("调价后", "D4", "0"),
    ] {
        assert!(matches!(&daily.updates[sheet].cells[cell], Cell::Number(v) if v == expected));
    }
    let output = dir.path().join("out.xlsx");
    workbook::write(&template, &output, &daily.updates).unwrap();
    let mut book = calamine::open_workbook_auto(output).unwrap();
    assert_eq!(
        book.worksheet_formula("调价后")
            .unwrap()
            .get_value((3, 7))
            .unwrap(),
        "D4*G4"
    );
}

#[test]
fn actual_price_change_uses_each_periods_source_price_in_daily() {
    let dir = tempfile::tempdir().unwrap();
    let mut req = price_change_fixture(dir.path());
    std::fs::write(
        dir.path().join("discounts.csv"),
        "油品,优惠\n0#柴油,0\n92#汽油,0\n95#汽油,0\n",
    )
    .unwrap();
    req.sources
        .insert("油品优惠".into(), dir.path().join("discounts.csv"));
    let template = daily_template_with_after(dir.path());
    let daily = report::daily(&req, &template).unwrap();
    for (sheet, cell, expected) in [
        ("调价前", "D3", "10"),
        ("调价前", "G3", "8"),
        ("调价后", "D3", "10"),
        ("调价后", "G3", "9"),
        ("调价后", "G5", "11"),
    ] {
        assert!(
            matches!(&daily.updates[sheet].cells[cell], Cell::Number(v) if v == expected),
            "{sheet} {cell}"
        );
    }
    let path = dir.path().join("details.csv");
    let original = std::fs::read_to_string(&path).unwrap();
    std::fs::write(&path, original.replace("2026-10-20 12:00:00", "bad-time")).unwrap();
    assert!(format!("{:#}", report::daily(&req, &template).unwrap_err()).contains("加油完成时间"));
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
        ("D13", "96.67"),
    ] {
        assert_eq!(value(&r, cell), expected, "{cell}");
    }
    assert!(matches!(r.updates["Sheet1"].cells["B8"], Cell::Blank));
    assert!(!r.updates["Sheet1"].cells.contains_key("B10"));
}
#[test]
fn online_recharge_includes_gifts_refunds_and_payment_labels() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    std::fs::write(
        dir.path().join("recharge.csv"),
        "原余额,充值金额,充值赠送,付款方式\n100,18144,240,微信收款\n100,3700,0,支付宝收款\n100,-300,-30,微信退款\n100,600,30,线上支付宝收款\n100,999,99,现金收款\n",
    )
    .unwrap();
    let report = report::simple(&request(dir.path())).unwrap();
    assert_eq!(value(&report, "B12"), "7461.33");
}

#[test]
fn no_card_uses_actual_receipts_ignores_balance_and_excludes_tank_returns() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    std::fs::write(
        dir.path().join("stats.csv"),
        "机号,油品,加油升,加油元,次数\n1,0#柴油,10,80,1\n2,92#汽油,40,360,4\n3,95#汽油,30,300,3\n",
    )
    .unwrap();
    std::fs::write(dir.path().join("details.csv"), "油品,单价,升数,油机金额,结算金额,优惠金额,收款方式,IC卡余额,卡号,实收金额\n0#柴油,8,10,80,80,0,现金收款,0,0,70\n92#汽油,9,10,90,0,0,现金收款,0,0,0\n92#汽油,9,10,90,85,5,现金收款,0,0,80\n95#汽油,10,10,100,100,0,充值卡收款,200,0,93\n92#汽油,9,10,90,90,0,现金收款,10,0,90\n95#汽油,10,10,100,100,0,回罐收款  ,0,9321,100\n92#汽油,9,10,90,90,0,现金收款,0,123,90\n95#汽油,10,10,100,100,0,回灌收款,0,0,100\n").unwrap();
    let mut req = request(dir.path());
    req.count_divisor = "1".into();
    let report = report::simple(&req).unwrap();
    assert_eq!(value(&report, "B13"), "3");
    assert_eq!(value(&report, "D13"), "91");
}

#[test]
fn no_card_does_not_require_or_validate_card_balance() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let path = dir.path().join("details.csv");
    let data = std::fs::read_to_string(&path).unwrap();
    for invalid in ["", "bad", "NaN", "Infinity"] {
        std::fs::write(
            &path,
            data.replace("现金收款,0,290", &format!("现金收款,{invalid},290")),
        )
        .unwrap();
        assert_eq!(
            value(&report::simple(&request(dir.path())).unwrap(), "D13"),
            "96.67"
        );
    }
    std::fs::write(&path, data.replace("IC卡余额", "余额备注")).unwrap();
    assert_eq!(
        value(&report::simple(&request(dir.path())).unwrap(), "D13"),
        "96.67"
    );
}

#[test]
fn no_card_requires_actual_receipts_instead_of_falling_back_to_settlement() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let path = dir.path().join("details.csv");
    let data = std::fs::read_to_string(&path).unwrap();
    for invalid in ["", "bad", "NaN", "Infinity"] {
        std::fs::write(
            &path,
            data.replace("现金收款,0,290", &format!("现金收款,0,{invalid}")),
        )
        .unwrap();
        let error = report::simple(&request(dir.path())).unwrap_err();
        assert!(format!("{error:#}").contains("实收金额"));
    }
    std::fs::write(&path, data.replace("实收金额", "收款备注")).unwrap();
    let error = report::simple(&request(dir.path())).unwrap_err();
    assert!(format!("{error:#}").contains("实收金额"));
}

#[test]
fn simple_uses_first_sheet_with_optional_matching_detail_page() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let second_sheet = regex::Regex::new(r#"<sheet name="Sheet2"[^>]*/>"#).unwrap();
    for (names, detail) in [
        (vec!["Sheet3", "Sheet1"], false),
        (vec!["Sheet2", "Sheet1"], true),
        (vec!["改名主表", "改名明细"], true),
        (vec!["首张"], false),
    ] {
        let template = dir.path().join("simple.xlsx");
        let fixture = Path::new(env!("CARGO_MANIFEST_DIR")).join("../app/fixtures/simple.xlsx");
        let mut input = ZipArchive::new(File::open(fixture).unwrap()).unwrap();
        let mut output = ZipWriter::new(File::create(&template).unwrap());
        for i in 0..input.len() {
            let mut entry = input.by_index(i).unwrap();
            let name = entry.name().to_owned();
            let mut bytes = vec![];
            entry.read_to_end(&mut bytes).unwrap();
            if name == "xl/workbook.xml" {
                let mut xml = String::from_utf8(bytes).unwrap();
                if names.len() == 1 {
                    xml = second_sheet.replace(&xml, "").into_owned();
                }
                xml = xml
                    .replace("name=\"Sheet1\"", "name=\"__first__\"")
                    .replace(
                        "name=\"Sheet2\"",
                        &format!("name=\"{}\"", names.last().unwrap()),
                    )
                    .replace("name=\"__first__\"", &format!("name=\"{}\"", names[0]));
                bytes = xml.into_bytes();
            } else if name == "xl/worksheets/sheet2.xml" && !detail {
                bytes = String::from_utf8(bytes)
                    .unwrap()
                    .replace("油品", "保留数据")
                    .into_bytes();
            }
            output
                .start_file(name, SimpleFileOptions::default())
                .unwrap();
            output.write_all(&bytes).unwrap();
        }
        output.finish().unwrap();
        let result = report::simple_for_template(&request(dir.path()), &template).unwrap();
        assert_eq!(result.updates.len(), if detail { 2 } else { 1 });
        assert!(matches!(&result.updates[names[0]].cells["D11"], Cell::Number(n) if n == "164"));
        if detail {
            assert!(result.updates[names[1]].cells.contains_key("D5"));
        }
        let path = dir.path().join("output.xlsx");
        workbook::write(&template, &path, &result.updates).unwrap();
        let mut book = calamine::open_workbook_auto(&path).unwrap();
        assert_eq!(book.sheet_names(), names);
        assert_eq!(
            book.worksheet_range_at(0)
                .unwrap()
                .unwrap()
                .get_value((10, 3))
                .unwrap()
                .to_string(),
            "164"
        );
        let mut changed = vec![
            "xl/worksheets/sheet1.xml",
            "xl/workbook.xml",
            "xl/styles.xml",
        ];
        if detail {
            changed.push("xl/worksheets/sheet2.xml");
        }
        preserved(&template, &path, &changed);
    }
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
    let result = report::simple(&req).unwrap();
    assert_eq!(value(&result, "G8"), "0");
    assert!(!result.updates["Sheet1"].cells.contains_key("G7"));
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
#[ignore = "requires private .context/attachments samples"]
fn verified_oct20_values_and_output_preservation() {
    let base = source_dir();
    let template = base.join("0LPzc8/T-CD简20(1).xlsx");
    assert!(
        template.exists(),
        "missing private sample: {}",
        template.display()
    );
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
    assert_eq!(value(&result, "D13"), "1550.99");
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
    minimal_with_sheet(
        path,
        r#"<worksheet><sheetData><row r="1"><c r="A1" s="0"><v>7</v></c></row><row r="2"/></sheetData><mergeCells><mergeCell ref="A1:B1"/></mergeCells></worksheet>"#,
    );
}
fn minimal_with_sheet(path: &Path, sheet: &str) {
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
        ("xl/worksheets/sheet1.xml", sheet),
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
fn sparse_rows_insert_before_updated_cells_and_preserve_styles() {
    let dir = tempfile::tempdir().unwrap();
    for (inserted, existing, row) in [("A3", "B3", 3), ("G2", "J2", 2)] {
        let template = dir.path().join(format!("template-{row}.xlsx"));
        minimal_with_sheet(
            &template,
            &format!(
                r#"<worksheet><sheetData><row r="{row}"><c r="{existing}" s="0"><v>7</v></c></row></sheetData></worksheet>"#
            ),
        );
        let update = SheetUpdate {
            cells: BTreeMap::from([
                (inserted.into(), Cell::Number("10".into())),
                (existing.into(), Cell::Number("20".into())),
            ]),
            formats: BTreeMap::from([(inserted.into(), 2)]),
        };
        let updates = Updates::from([("Sheet1".into(), update)]);
        let output = dir.path().join(format!("output-{row}.xlsx"));
        workbook::write(&template, &output, &updates).unwrap();
        preserved(
            &template,
            &output,
            &[
                "xl/worksheets/sheet1.xml",
                "xl/styles.xml",
                "xl/workbook.xml",
            ],
        );
        let mut zip = ZipArchive::new(File::open(&output).unwrap()).unwrap();
        let mut sheet = String::new();
        zip.by_name("xl/worksheets/sheet1.xml")
            .unwrap()
            .read_to_string(&mut sheet)
            .unwrap();
        let doc = roxmltree::Document::parse(&sheet).unwrap();
        let cells: Vec<_> = doc.descendants().filter(|n| n.has_tag_name("c")).collect();
        assert_eq!(cells.len(), 2);
        for (cell, address, value, style) in [
            (cells[0], inserted, "10", "1"),
            (cells[1], existing, "20", "0"),
        ] {
            assert_eq!(cell.attribute("r"), Some(address));
            assert_eq!(cell.attribute("s"), Some(style));
            assert_eq!(cell.first_element_child().unwrap().text(), Some(value));
        }
    }
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
#[ignore = "requires private .context/attachments samples"]
fn reads_real_grouped_xls() {
    let p = source_dir().join("ZRUN60/2(1).xls");
    assert!(p.exists(), "missing private sample: {}", p.display());
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
#[ignore = "requires private .context/attachments samples"]
fn real_embedded_screenshots_survive_a_template_edit() {
    for relative in ["a8JA1z/1(3).xlsx", "But3s4/4(3).xlsx"] {
        let path = source_dir().join(relative);
        assert!(path.exists(), "missing private sample: {}", path.display());
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
        (
            "国通1".into(),
            serde_json::json!({"订单金额":"300元","退款订单金额":"30元"}),
        ),
        (
            "国通1".into(),
            serde_json::json!({"订单金额":null,"退款订单金额":null,"交易明细金额合计":"13,307.06"}),
        ),
        ("国通2".into(), serde_json::json!({"交易明细金额合计":-3})),
        ("超市销售收入".into(), serde_json::json!({"现金":"587.70"})),
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
    assert_eq!(number("调价前", "H92"), "4525.69");
    assert_eq!(number("调价前", "H93"), "-1");
    assert_eq!(number("调价前", "H71"), "195.9");
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
