use calamine::Reader;
use financial_engine::{Cell, Request, Updates, receipts, report, source, workbook};
use std::{
    collections::BTreeMap,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
};
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};

fn fixture(root: &Path) -> Request {
    for (name, data) in [
        (
            "stats",
            "机号,油品,加油升,加油元,次数\n3,0#柴油,30,240,1\n9,92#汽油,30,270,1\n11,95#汽油,30,300,1\n",
        ),
        (
            "details",
            "油品,单价,升数,油机金额,结算金额,优惠金额,收款方式,实收金额\n0#柴油,8,30,240,234,6,充值卡收款,230\n92#汽油,9,30,270,258,9,电子卡收款,250\n95#汽油,10,30,300,300,0,现金收款,290\n",
        ),
        (
            "recharge",
            "原余额,充值金额,充值赠送,付款方式\n100,3000,0,现金收款\n100,600,0,微信收款\n",
        ),
        ("discounts", "油品,优惠\n0#柴油,6\n92#汽油,12\n95#汽油,0\n"),
    ] {
        fs::write(root.join(format!("{name}.csv")), data).unwrap();
    }
    Request {
        sources: BTreeMap::from([
            ("油品时间统计".into(), root.join("stats.csv")),
            ("加油明细".into(), root.join("details.csv")),
            ("充值明细".into(), root.join("recharge.csv")),
            ("油品优惠".into(), root.join("discounts.csv")),
        ]),
        day: 20,
        divisor: "3".into(),
        count_divisor: "3".into(),
        closing_balance: String::new(),
    }
}

fn replace(path: &Path, from: &str, to: &str) {
    let data = fs::read_to_string(path).unwrap();
    assert!(data.contains(from));
    fs::write(path, data.replace(from, to)).unwrap();
}

fn template(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../app/fixtures")
        .join(name)
}

#[test]
fn presentation_changes_keep_the_same_report_and_reconciliation() {
    let dir = tempfile::tempdir().unwrap();
    let baseline = serde_json::to_value(report::simple(&fixture(dir.path())).unwrap()).unwrap();
    for case in 0..4 {
        let req = fixture(dir.path());
        match case {
            0 => {
                let p = dir.path().join("stats.csv");
                let data = fs::read_to_string(&p).unwrap();
                fs::write(p, format!("{}{data}", "导出说明\n".repeat(15))).unwrap();
            }
            1 => replace(&dir.path().join("stats.csv"), "加油升", "\"加油\n升\""),
            2 => replace(&dir.path().join("recharge.csv"), "3000", "\"3,000\""),
            _ => {
                for name in ["stats", "details", "discounts"] {
                    replace(
                        &dir.path().join(format!("{name}.csv")),
                        "92#汽油",
                        "92＃ 汽油",
                    );
                }
            }
        }
        assert_eq!(
            serde_json::to_value(report::simple(&req).unwrap()).unwrap(),
            baseline
        );
        replace(&dir.path().join("details.csv"), "240,234", "241,234");
        assert!(format!("{:#}", report::simple(&req).unwrap_err()).contains("油机金额不一致"));
    }
}

#[test]
fn grouping_and_header_normalization_do_not_hide_invalid_inputs() {
    for (text, expected) in [
        ("1,234.50", "1234.50"),
        ("-1，234.50", "-1234.50"),
        ("1e3", "1000"),
    ] {
        assert_eq!(
            source::number(text).unwrap(),
            source::number(expected).unwrap()
        );
    }
    for text in ["12,34", "1,23,456", "1,,000", ",123", "1,000.0.1", ""] {
        assert!(source::number(text).is_err(), "{text}");
    }
    let dir = tempfile::tempdir().unwrap();
    let req = fixture(dir.path());
    replace(&dir.path().join("stats.csv"), "次数", "次数,次 数");
    assert!(format!("{:#}", report::simple(&req).unwrap_err()).contains("表头字段重复"));
    fixture(dir.path());
    replace(&dir.path().join("stats.csv"), "92#汽油", "98#汽油");
    assert!(format!("{:#}", report::simple(&req).unwrap_err()).contains("未支持的油品"));
    fixture(dir.path());
    replace(&dir.path().join("recharge.csv"), "充值金额", "备注");
    assert!(format!("{:#}", report::simple(&req).unwrap_err()).contains("找不到表头"));
}

#[test]
fn empty_gifts_match_zero_in_both_reports_but_missing_amounts_still_fail() {
    let dir = tempfile::tempdir().unwrap();
    let req = fixture(dir.path());
    let simple = serde_json::to_value(report::simple(&req).unwrap()).unwrap();
    let daily =
        serde_json::to_value(report::daily(&req, &template("daily.xlsx")).unwrap()).unwrap();
    replace(
        &dir.path().join("recharge.csv"),
        "3000,0,现金",
        "3000,,现金",
    );
    assert_eq!(
        serde_json::to_value(report::simple(&req).unwrap()).unwrap(),
        simple
    );
    assert_eq!(
        serde_json::to_value(report::daily(&req, &template("daily.xlsx")).unwrap()).unwrap(),
        daily
    );
    for (from, to, message) in [
        ("3000,,现金", "3000,未知,现金", "充值赠送"),
        ("3000,未知,现金", ",0,现金", "充值金额"),
        ("充值赠送", "备注", "找不到表头"),
    ] {
        replace(&dir.path().join("recharge.csv"), from, to);
        assert!(format!("{:#}", report::simple(&req).unwrap_err()).contains(message));
    }
}

fn yf_template(root: &Path) -> PathBuf {
    let mut changes = Updates::new();
    for (sheet, cells) in [
        (
            "Sheet1",
            vec![
                ("A1", "T-YF"),
                ("A12", "线充"),
                ("C12", "线消"),
                ("C13", "无卡金额"),
            ],
        ),
        (
            "Sheet2",
            vec![
                ("A3", "油品"),
                ("B3", "升数"),
                ("C3", "次数"),
                ("A4", "0#"),
                ("A5", "92#"),
                ("A6", "95#"),
                ("A9", "充值明细"),
                ("A10", "200"),
                ("A21", "汽油"),
                ("A22", "升数"),
                ("D22", "会员优惠"),
                ("E22", "总优惠"),
                ("F22", "平均优惠"),
                ("A24", "柴油"),
                ("A25", "升数"),
                ("C25", "会员优惠"),
                ("E25", "总优惠"),
                ("F25", "平均优惠"),
                ("D7", "保留"),
                ("G31", "保留"),
            ],
        ),
    ] {
        for (address, text) in cells {
            changes
                .entry(sheet.into())
                .or_default()
                .cells
                .insert(address.into(), Cell::Text(text.into()));
        }
    }
    let target = root.join("yf.xlsx");
    workbook::write(&template("simple.xlsx"), &target, &changes).unwrap();
    target
}

#[test]
fn yf_title_is_accepted_without_writing_the_second_page() {
    let dir = tempfile::tempdir().unwrap();
    let mut req = fixture(dir.path());
    req.closing_balance = "300".into();
    let template = yf_template(dir.path());
    let result = report::simple_for_template(&req, &template).unwrap();
    assert_eq!(result.updates.len(), 1);
    assert!(!result.updates.contains_key("Sheet2"));
    let saved = dir.path().join("saved.xlsx");
    workbook::write(&template, &saved, &result.updates).unwrap();
    let mut book = calamine::open_workbook_auto(&saved).unwrap();
    let first = book.worksheet_range("Sheet1").unwrap();
    assert_eq!(first.get_value((0, 0)).unwrap().to_string(), "T-YF");
    assert_eq!(first.get_value((7, 6)).unwrap().to_string(), "100");
    drop(book);
    let part = |path: &Path| {
        let mut zip = ZipArchive::new(fs::File::open(path).unwrap()).unwrap();
        let mut bytes = vec![];
        zip.by_name("xl/worksheets/sheet2.xml")
            .unwrap()
            .read_to_end(&mut bytes)
            .unwrap();
        bytes
    };
    assert_eq!(part(&template), part(&saved));
    let mut broken = Updates::new();
    broken
        .entry("Sheet1".into())
        .or_default()
        .cells
        .insert("C12".into(), Cell::Text("其他".into()));
    workbook::write(&template, &dir.path().join("wrong.xlsx"), &broken).unwrap();
    assert!(workbook::validate_simple_template(&dir.path().join("wrong.xlsx")).is_err());
}

#[test]
fn daily_sheet_spacing_works_for_reading_receipts_and_writing_without_guessing_names() {
    let dir = tempfile::tempdir().unwrap();
    let req = fixture(dir.path());
    let original = template("daily.xlsx");
    let renamed = dir.path().join("renamed.xlsx");
    let mut source = ZipArchive::new(fs::File::open(&original).unwrap()).unwrap();
    let mut writer = ZipWriter::new(fs::File::create(&renamed).unwrap());
    for i in 0..source.len() {
        let mut entry = source.by_index(i).unwrap();
        let name = entry.name().to_owned();
        let mut bytes = vec![];
        entry.read_to_end(&mut bytes).unwrap();
        if name.ends_with(".xml") {
            bytes = String::from_utf8(bytes)
                .unwrap()
                .replace("油品优惠明细 2", "油品优惠明细2")
                .replace("调价前", "调价 前")
                .into_bytes();
        }
        writer
            .start_file(name, SimpleFileOptions::default())
            .unwrap();
        writer.write_all(&bytes).unwrap();
    }
    writer.finish().unwrap();
    let mut result = report::daily(&req, &renamed).unwrap();
    assert_eq!(
        serde_json::to_value(&result).unwrap(),
        serde_json::to_value(report::daily(&req, &original).unwrap()).unwrap()
    );
    receipts::apply_many(
        &mut result,
        &renamed,
        20,
        source::number("0").unwrap(),
        &[("超市销售收入".into(), serde_json::json!({"现金":"300"}))],
    )
    .unwrap();
    let output = dir.path().join("saved.xlsx");
    workbook::write(&renamed, &output, &result.updates).unwrap();
    let mut book = calamine::open_workbook_auto(&output).unwrap();
    assert!(book.sheet_names().contains(&"油品优惠明细2".to_owned()));
    assert_eq!(
        book.worksheet_range("调价 前")
            .unwrap()
            .get_value((70, 7))
            .unwrap()
            .to_string(),
        "100"
    );
    assert!(
        workbook::sheet_name(
            &["油品优惠明细2".into(), "油品 优惠明细2".into()],
            "油品优惠明细 2"
        )
        .is_err()
    );
    assert!(workbook::sheet_name(&["其他".into()], "调价前").is_err());
    let mut conflict = result.updates.clone();
    conflict.insert("调价 前".into(), Default::default());
    let untouched = dir.path().join("untouched.xlsx");
    fs::write(&untouched, b"keep").unwrap();
    assert!(workbook::write(&renamed, &untouched, &conflict).is_err());
    assert_eq!(fs::read(untouched).unwrap(), b"keep");
}
