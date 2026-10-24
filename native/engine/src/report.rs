use crate::{
    Cell, Report, Request, SheetUpdate, Updates,
    source::{self, Row, Table, num, number, text},
};
use anyhow::{Context, Result, bail};
use rust_decimal::{Decimal as D, RoundingStrategy};
use std::collections::{BTreeMap, BTreeSet};

pub const FUELS: [&str; 3] = ["0#柴油", "92#汽油", "95#汽油"];
pub fn round(v: D, dp: u32) -> D {
    v.round_dp_with_strategy(dp, RoundingStrategy::MidpointAwayFromZero)
}
fn sum<'a>(rows: impl Iterator<Item = &'a Row>, key: &str) -> Result<D> {
    rows.map(|r| num(r, key)).sum()
}
fn online_recharge(recharge: &Table, scale: D) -> Result<D> {
    let selected: Vec<_> = recharge
        .rows
        .iter()
        .filter(|row| {
            let method = text(row, "付款方式");
            method.contains("微信") || method.contains("支付宝")
        })
        .collect();
    Ok(
        ((sum(selected.iter().copied(), "充值金额")? + sum(selected.iter().copied(), "充值赠送")?)
            / scale)
            .round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven),
    )
}
fn put(s: &mut SheetUpdate, key: impl Into<String>, value: D) {
    s.cells
        .insert(key.into(), Cell::Number(value.normalize().to_string()));
}
fn formula(s: &mut SheetUpdate, key: impl Into<String>, value: impl Into<String>) {
    s.cells.insert(key.into(), Cell::Formula(value.into()));
}
fn load(
    req: &Request,
    category: &str,
    required: &[&str],
    numeric: &[&str],
    discount: bool,
) -> Result<Table> {
    source::read(
        req.sources
            .get(category)
            .with_context(|| format!("缺少源表：{category}"))?,
        required,
        numeric,
        discount,
    )
}
fn scales(req: &Request) -> Result<(D, D)> {
    let a = number(&req.divisor)?;
    let b = number(&req.count_divisor)?;
    if a <= D::ZERO || b <= D::ZERO {
        bail!("折算除数必须大于零")
    }
    if !(1..=31).contains(&req.day) {
        bail!("日期必须在 1 至 31 之间")
    }
    Ok((a, b))
}
fn simple_statistics(req: &Request) -> Result<(Table, Vec<Table>)> {
    let read = |category| {
        load(
            req,
            category,
            &["机号", "油品", "加油升", "加油元", "次数"],
            &["机号", "加油升", "加油元", "次数"],
            false,
        )
    };
    let mut parts = vec![read("油品时间统计")?];
    if req.sources.contains_key("油品时间统计(调价后)") {
        parts.push(read("油品时间统计(调价后)")?);
    }
    let stations: BTreeSet<_> = parts
        .iter()
        .filter(|part| !part.stations.is_empty())
        .map(|part| &part.stations)
        .collect();
    if stations.len() > 1 {
        bail!("源表站号不一致");
    }
    let period = if parts.iter().all(|part| part.period.len() == 2) {
        vec![
            parts.iter().map(|part| part.period[0]).min().unwrap(),
            parts.iter().map(|part| part.period[1]).max().unwrap(),
        ]
    } else {
        vec![]
    };
    let combined = Table {
        rows: parts
            .iter()
            .flat_map(|part| part.rows.iter().cloned())
            .collect(),
        period,
        stations: stations
            .first()
            .map(|stations| (*stations).clone())
            .unwrap_or_default(),
    };
    Ok((combined, parts))
}
pub fn simple(req: &Request) -> Result<Report> {
    let (scale, counts) = scales(req)?;
    let (stats, statistics) = simple_statistics(req)?;
    let details = load(
        req,
        "加油明细",
        &[
            "油品",
            "单价",
            "升数",
            "油机金额",
            "结算金额",
            "优惠金额",
            "收款方式",
            "实收金额",
        ],
        &["单价", "升数", "油机金额", "结算金额", "优惠金额"],
        false,
    )?;
    let recharge = load(
        req,
        "充值明细",
        &["原余额", "充值金额", "充值赠送", "付款方式"],
        &["原余额", "充值金额", "充值赠送"],
        false,
    )?;
    let discount = if req.sources.contains_key("油品优惠") {
        Some(load(req, "油品优惠", &["油品", "优惠"], &["优惠"], true)?)
    } else {
        None
    };
    source::consistent(&[&stats, &details, &recharge])?;
    for table in [&stats, &details].into_iter().chain(discount.as_ref()) {
        for row in &table.rows {
            if !FUELS.contains(&text(row, "油品")) {
                bail!("未支持的油品：{}", text(row, "油品"))
            }
        }
    }
    let groups = crate::fuel::groups(&statistics, &details)?;
    let mut first = SheetUpdate::default();
    let mut second = SheetUpdate::default();
    put(&mut first, "C2", req.day.into());
    for (i, fuel) in FUELS.iter().enumerate() {
        let row = i + 3;
        let s: Vec<_> = stats
            .rows
            .iter()
            .filter(|r| text(r, "油品") == *fuel)
            .collect();
        let d: Vec<_> = details
            .rows
            .iter()
            .filter(|r| text(r, "油品") == *fuel)
            .collect();
        for (metric, actual, expected) in [
            (
                "升数",
                sum(s.iter().copied(), "加油升")?,
                sum(d.iter().copied(), "升数")?,
            ),
            (
                "油机金额",
                sum(s.iter().copied(), "加油元")?,
                sum(d.iter().copied(), "油机金额")?,
            ),
            ("次数", sum(s.iter().copied(), "次数")?, D::from(d.len())),
        ] {
            let tolerance = if metric == "次数" {
                D::ZERO
            } else {
                D::new(11, 3)
            };
            if (actual - expected).abs() > tolerance {
                bail!("{fuel} {metric}不一致：{actual} / {expected}")
            }
        }
        if let Some(discounts) = &discount {
            let actual = sum(
                discounts.rows.iter().filter(|r| text(r, "油品") == *fuel),
                "优惠",
            )?;
            let expected =
                sum(d.iter().copied(), "油机金额")? - sum(d.iter().copied(), "结算金额")?;
            if (actual - expected).abs() > D::new(11, 3) {
                bail!("{fuel} 优惠不一致：{actual} / {expected}")
            }
        }
        let selected: Vec<_> = groups.iter().filter(|group| group.fuel == *fuel).collect();
        let litres: D = selected.iter().map(|group| group.litres(scale)).sum();
        let amount = round(
            selected
                .iter()
                .map(|group| group.litres(scale) * group.price)
                .sum(),
            2,
        );
        first
            .cells
            .insert(format!("A{row}"), Cell::Text(fuel.to_string()));
        put(&mut first, format!("B{row}"), litres);
        put(&mut first, format!("D{row}"), amount);
        put(
            &mut first,
            format!("E{row}"),
            round(sum(s.iter().copied(), "次数")? / counts, 0),
        );
        first.formats.insert(format!("E{row}"), 0);
        formula(
            &mut first,
            format!("C{row}"),
            format!("IF(B6=0,0,B{row}/B6)"),
        );
        formula(
            &mut first,
            format!("F{row}"),
            format!("IF(E{row}=0,0,D{row}/E{row})"),
        );
        let r = row + 2;
        formula(
            &mut second,
            format!("D{r}"),
            format!("IF(C{r}=0,0,B{r}/C{r})"),
        );
    }
    first.formats.insert("E6".into(), 0);
    for (k, f) in [
        ("F6", "IF(E6=0,0,D6/E6)"),
        ("F13", "IF(SUM(D4:D5)=0,0,D13/SUM(D4:D5))"),
        ("F11", "IF(D6=0,0,D11/D6)"),
        ("F12", "IF(D6=0,0,D12/D6)"),
    ] {
        formula(&mut first, k, f);
    }
    let card = round(
        sum(
            details
                .rows
                .iter()
                .filter(|r| text(r, "收款方式") == "充值卡收款"),
            "结算金额",
        )? / scale,
        2,
    );
    let online = round(
        sum(
            details
                .rows
                .iter()
                .filter(|r| text(r, "收款方式") == "电子卡收款"),
            "结算金额",
        )? / scale,
        2,
    );
    put(&mut first, "D11", card + online);
    put(&mut first, "D12", online);
    let no_card: Vec<_> = details
        .rows
        .iter()
        .filter(|r| {
            num(r, "优惠金额").is_ok_and(|v| v == D::ZERO)
                && num(r, "结算金额").is_ok_and(|v| v != D::ZERO)
                && ["92#汽油", "95#汽油"].contains(&text(r, "油品"))
                && !["回罐收款", "回灌收款"].contains(&text(r, "收款方式"))
        })
        .collect();
    put(&mut first, "B13", round(D::from(no_card.len()) / counts, 0));
    first.formats.insert("B13".into(), 0);
    put(
        &mut first,
        "D13",
        round(sum(no_card.into_iter(), "实收金额")? / scale, 2),
    );
    for (is_new, count_cell, amount_cell) in [(true, "B8", "D8"), (false, "B9", "D9")] {
        let selected: Vec<_> = recharge
            .rows
            .iter()
            .filter(|r| {
                ["现金收款", "微信收款", "支付宝收款"].contains(&text(r, "付款方式"))
                    && num(r, "原余额").is_ok_and(|v| (v == D::ZERO) == is_new)
            })
            .collect();
        first.formats.insert(count_cell.into(), 2);
        if is_new && selected.is_empty() {
            first.cells.insert(count_cell.into(), Cell::Blank);
            first.cells.insert(amount_cell.into(), Cell::Blank);
        } else {
            let count = if is_new {
                selected.len()
            } else {
                recharge.rows.len()
            };
            put(&mut first, count_cell, round(D::from(count) / counts, 2));
            put(
                &mut first,
                amount_cell,
                round(
                    (sum(selected.iter().copied(), "充值金额")?
                        + sum(selected.iter().copied(), "充值赠送")?)
                        / scale,
                    2,
                ),
            );
        }
    }
    put(&mut first, "B12", online_recharge(&recharge, scale)?);
    if !req.closing_balance.trim().is_empty() {
        put(
            &mut first,
            "G8",
            round(number(&req.closing_balance)? / scale, 2),
        );
        first.formats.insert("G8".into(), 2);
    }
    if let Some(discounts) = discount {
        for (fuels, cell) in [(vec!["92#汽油", "95#汽油"], "D31"), (vec!["0#柴油"], "D34")] {
            put(
                &mut second,
                cell,
                round(
                    sum(
                        discounts
                            .rows
                            .iter()
                            .filter(|r| fuels.contains(&text(r, "油品"))),
                        "优惠",
                    )? / scale,
                    2,
                ),
            );
        }
        formula(&mut second, "G31", "IF(A31=0,0,F31/A31)");
        formula(&mut second, "G34", "IF(A34=0,0,F34/A34)");
    }
    Ok(Report {
        updates: BTreeMap::from([("Sheet1".into(), first), ("Sheet2".into(), second)]),
        notes: vec![
            "源表升数、油机金额、次数交叉校验通过".into(),
            "卡消费使用结算金额；无卡使用实收金额，不筛选余额，排除回罐；充值包含赠送".into(),
        ],
    })
}

/// Resolve worksheet positions before writing a station's simple template.
pub fn simple_for_template(req: &Request, template: &std::path::Path) -> Result<Report> {
    let (main, detail) = crate::workbook::simple_template_sheets(template)?;
    let mut report = simple(req)?;
    let first = report
        .updates
        .remove("Sheet1")
        .context("缺少简表主表数据")?;
    let second = report
        .updates
        .remove("Sheet2")
        .context("缺少简表明细数据")?;
    report.updates.insert(main, first);
    if let Some(detail) = detail {
        report.updates.insert(detail, second);
    } else {
        report
            .notes
            .push("已填写第一个工作表；其他页保留原值".into());
    }
    Ok(report)
}

/// Legacy report retains its own mapping and rounding policy.
pub fn daily(req: &Request, template: &std::path::Path) -> Result<Report> {
    scales(req)?;
    let mut book = calamine::open_workbook_auto(template)?;
    use calamine::Reader;
    // C68 may allocate part of the cash recharge to C72 (corporate recharge).
    // The template owns that allocation when it supplies a formula.
    let preserve_cash_formula = book
        .worksheet_formula("调价前")?
        .get_value((67, 2))
        .is_some_and(|formula| !formula.trim().is_empty());
    let mut updates = Updates::new();
    let mut first = SheetUpdate::default();
    let scale = D::from(3);
    let legacy = |v: D| v.round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven);
    let (_, statistics) = simple_statistics(req)?;
    let details = load(
        req,
        "加油明细",
        &["油品", "单价", "结算金额", "收款方式"],
        &["单价", "结算金额"],
        false,
    )?;
    let groups = crate::fuel::groups(&statistics, &details)?;
    for (period, sheet) in [(0, "调价前"), (1, "调价后")] {
        if period == 1 && statistics.len() < 2 {
            continue;
        }
        let range = book.worksheet_range(sheet)?;
        let mut out = SheetUpdate::default();
        let mut positions = BTreeMap::new();
        let mut section = String::new();
        let (sr, sc) = range.start().unwrap_or_default();
        for (r, c, cell) in range.used_cells() {
            let (rr, cc) = (r + sr as usize, c + sc as usize);
            if cc == 0 && !cell.to_string().is_empty() {
                section = cell.to_string().trim().to_string();
            }
            if rr >= 2
                && cc == 1
                && ["A", "B", "C"].contains(&section.as_str())
                && let Ok(machine) = number(cell.to_string().trim().trim_end_matches('号'))
            {
                positions.insert((section.clone(), machine), rr + 1);
                put(&mut out, format!("D{}", rr + 1), D::ZERO);
            }
        }
        for group in groups.iter().filter(|group| group.period == period) {
            let section = match group.fuel {
                "0#柴油" => "A",
                "92#汽油" => "B",
                "95#汽油" => "C",
                _ => unreachable!(),
            };
            for (machine, litres) in &group.machines {
                let row = positions
                    .get(&(section.into(), *machine))
                    .with_context(|| format!("{sheet} 找不到油枪 {machine} / {section}"))?;
                put(&mut out, format!("D{row}"), round(*litres / scale, 2));
                // The source price, rather than a previous day's template value, owns this calculation.
                put(&mut out, format!("G{row}"), group.price);
            }
        }
        updates.insert(sheet.into(), out);
    }
    for (method, cell) in [("充值卡收款", "H76"), ("电子卡收款", "H78")] {
        put(
            &mut first,
            cell,
            legacy(
                sum(
                    details
                        .rows
                        .iter()
                        .filter(|r| text(r, "收款方式") == method),
                    "结算金额",
                )? / scale,
            ),
        );
    }
    let mut recharge = load(
        req,
        "充值明细",
        &["充值金额", "充值赠送", "付款方式"],
        &[],
        false,
    )?;
    for row in &mut recharge.rows {
        for key in ["充值金额", "充值赠送"] {
            if text(row, key).is_empty() {
                row.insert(key.into(), "0".into());
            }
        }
    }
    for (online, cell) in [(true, "C73"), (false, "C68")] {
        if online {
            put(&mut first, cell, online_recharge(&recharge, scale)?);
            continue;
        }
        if cell == "C68" && preserve_cash_formula {
            continue;
        }
        let selected: Vec<_> = recharge
            .rows
            .iter()
            .filter(|r| text(r, "付款方式").contains("现金"))
            .collect();
        put(
            &mut first,
            cell,
            legacy(
                (sum(selected.iter().copied(), "充值金额")?
                    + sum(selected.iter().copied(), "充值赠送")?)
                    / scale,
            ),
        );
    }
    let discounts = load(req, "油品优惠", &["油品", "优惠"], &["优惠"], true)?;
    let range = book.worksheet_range("油品优惠明细 2")?;
    let day_row = range
        .used_cells()
        .find(|(r, c, v)| {
            *r + range.start().unwrap_or_default().0 as usize >= 1
                && *c + range.start().unwrap_or_default().1 as usize == 1
                && v.to_string() == req.day.to_string()
        })
        .map(|(r, _, _)| r + range.start().unwrap_or_default().0 as usize + 1)
        .context("优惠明细中找不到所选日期")?;
    let mut discount_sheet = SheetUpdate::default();
    for (fuels, col) in [(vec!["0#柴油"], "G"), (vec!["92#汽油", "95#汽油"], "J")] {
        put(
            &mut discount_sheet,
            format!("{col}{day_row}"),
            legacy(
                sum(
                    discounts
                        .rows
                        .iter()
                        .filter(|r| fuels.contains(&text(r, "油品"))),
                    "优惠",
                )? / scale,
            ),
        );
    }
    if req.sources.contains_key("通联") {
        let t = load(req, "通联", &["原始金额", "收支方向"], &["原始金额"], false)?;
        put(
            &mut first,
            "C86",
            legacy(
                sum(
                    t.rows.iter().filter(|r| text(r, "收支方向") == "收入"),
                    "原始金额",
                )? / scale,
            ),
        );
    }
    updates
        .entry("调价前".into())
        .or_default()
        .cells
        .extend(first.cells);
    updates.insert("油品优惠明细 2".into(), discount_sheet);
    Ok(Report {
        updates,
        notes: vec!["日报：按油枪和日期写入，消费使用结算金额".into()],
    })
}
