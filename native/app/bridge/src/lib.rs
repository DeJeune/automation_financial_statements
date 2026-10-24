//! Native desktop boundary. All workbook work executes off the UI thread.
mod preview;
mod recognition;
mod runtime;
mod save;
mod stations;
#[cfg(debug_assertions)]
mod test_files;
mod updater;
use anyhow::{Context, Result};
use financial_engine::{Cell, Report, Request, report, workbook};
use nsh_core::ui::prelude::*;
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
};

#[derive(Clone, JsObject)]
pub struct InputFile {
    pub category: String,
    pub path: String,
}
#[derive(Clone, JsObject)]
pub struct Job {
    pub batch_id: String,
    pub files: Vec<InputFile>,
    pub template: String,
    pub protected_files: Vec<String>,
    pub kind: String,
    pub daily_result_id: String,
    pub date: String,
    pub work_start: String,
    pub shift_time: String,
    pub divisor: String,
    pub count_divisor: String,
    pub balance: String,
    pub gas_price: String,
    pub api_key: String,
    pub api_base: String,
    pub model: String,
}
#[derive(Clone, JsObject)]
pub struct PreviewCell {
    pub sheet: String,
    pub address: String,
    pub value: String,
}
#[derive(Clone, JsObject)]
pub struct Prepared {
    pub id: String,
    pub kind: String,
    pub cells: Vec<PreviewCell>,
    pub notes: Vec<String>,
    pub saved_path: String,
    pub backup_path: String,
}
struct Snapshot {
    batch_id: String,
    kind: String,
    supermarket_files: Vec<String>,
    recharge_files: Vec<String>,
    directory: tempfile::TempDir,
    report: Report,
}
static SNAPSHOTS: OnceLock<Mutex<BTreeMap<String, Snapshot>>> = OnceLock::new();
type PastedFiles = BTreeMap<String, Vec<tempfile::NamedTempFile>>;
static PASTED: OnceLock<Mutex<PastedFiles>> = OnceLock::new();
static NEXT: AtomicU64 = AtomicU64::new(1);
fn snapshots() -> &'static Mutex<BTreeMap<String, Snapshot>> {
    SNAPSHOTS.get_or_init(|| Mutex::new(BTreeMap::new()))
}
fn path(value: &str) -> Result<PathBuf> {
    if value.starts_with("file:") {
        let uri = url::Url::parse(value)?;
        #[cfg(target_os = "macos")]
        if uri.path().starts_with("/.file/id=") {
            // Finder may put file-reference URLs on the clipboard. Their IDs are
            // resolved by Foundation, not by POSIX filesystem path traversal.
            use objc2_foundation::{NSString, NSURL};
            let resolved = NSURL::URLWithString(&NSString::from_str(value))
                .and_then(|url| url.filePathURL())
                .and_then(|url| url.absoluteString())
                .context("无法解析复制的文件引用，请重新复制原文件")?;
            let resolved = url::Url::parse(&resolved.to_string())?;
            anyhow::ensure!(
                !resolved.path().starts_with("/.file/id="),
                "无法解析复制的文件引用，请重新复制原文件"
            );
            return resolved
                .to_file_path()
                .map_err(|_| anyhow::anyhow!("无效文件路径"));
        }
        uri.to_file_path()
            .map_err(|_| anyhow::anyhow!("无效文件路径"))
    } else {
        Ok(value.into())
    }
}
fn supermarket_files(job: &Job) -> Vec<String> {
    job.files
        .iter()
        .filter(|file| file.category == "超市销售收入")
        .map(|file| file.path.clone())
        .collect()
}

fn recharge_files(job: &Job) -> Vec<String> {
    job.files
        .iter()
        .filter(|file| file.category == "充值明细")
        .map(|file| file.path.clone())
        .collect()
}

fn daily_online_recharge(job: &Job) -> Result<Option<Cell>> {
    if job.daily_result_id.is_empty() {
        return Ok(None);
    }
    let all = snapshots()
        .lock()
        .map_err(|_| anyhow::anyhow!("任务状态不可用"))?;
    let daily = all
        .get(&job.daily_result_id)
        .context("日报结果已失效，请重新处理")?;
    anyhow::ensure!(
        daily.kind == "daily" && daily.batch_id == job.batch_id,
        "线上充值必须来自当前加油站的日报结果"
    );
    anyhow::ensure!(
        daily.recharge_files == recharge_files(job),
        "充值明细已变化，请重新处理"
    );
    daily
        .report
        .updates
        .get("调价前")
        .and_then(|sheet| sheet.cells.get("C73"))
        .cloned()
        .map(Some)
        .context("日报结果没有线上充值金额，请重新处理")
}

fn daily_supermarket(job: &Job) -> Result<Option<Cell>> {
    if job.daily_result_id.is_empty() || supermarket_files(job).is_empty() {
        return Ok(None);
    }
    let all = snapshots()
        .lock()
        .map_err(|_| anyhow::anyhow!("任务状态不可用"))?;
    let daily = all
        .get(&job.daily_result_id)
        .context("日报结果已失效，请重新处理")?;
    anyhow::ensure!(
        daily.kind == "daily" && daily.batch_id == job.batch_id,
        "超市金额必须来自当前加油站的日报结果"
    );
    anyhow::ensure!(
        daily.supermarket_files == supermarket_files(job),
        "超市截图已变化，请重新处理"
    );
    daily
        .report
        .updates
        .get("调价前")
        .and_then(|sheet| sheet.cells.get("H71"))
        .cloned()
        .map(Some)
        .context("日报结果没有超市金额，请重新处理")
}

fn recognize_images(
    job: &Job,
    reuse_supermarket: bool,
) -> Result<Vec<(String, serde_json::Value)>> {
    let mut recognized = Vec::new();
    for file in &job.files {
        if !financial_engine::receipts::CATEGORIES.contains(&file.category.as_str())
            || (job.kind == "simple"
                && !["超市销售收入", "新系统卡余额"].contains(&file.category.as_str()))
            || (job.kind != "simple" && file.category == "新系统卡余额")
            || (reuse_supermarket && file.category == "超市销售收入")
        {
            continue;
        }
        if !recognized.is_empty() {
            std::thread::sleep(std::time::Duration::from_secs(6));
        }
        runtime::progress(
            &job.batch_id,
            &file.category,
            &file.path,
            "识别中",
            "正在读取截图",
        );
        let data = match recognition::recognize(
            &file.category,
            &path(&file.path)?,
            &job.api_base,
            &job.api_key,
            &job.model,
        ) {
            Ok(data) => data,
            Err(e) => {
                runtime::progress(
                    &job.batch_id,
                    &file.category,
                    &file.path,
                    "失败",
                    format!("{e:#}"),
                );
                return Err(e);
            }
        };
        let detail = financial_engine::receipts::fields(&file.category)?
            .iter()
            .map(|key| {
                format!(
                    "{key}: {}",
                    data[*key]
                        .as_str()
                        .map(str::to_owned)
                        .unwrap_or_else(|| data[*key].to_string())
                )
            })
            .collect::<Vec<_>>()
            .join("；");
        runtime::progress(&job.batch_id, &file.category, &file.path, "完成", detail);
        recognized.push((file.category.clone(), data));
    }
    Ok(recognized)
}

fn prepare(job: Job) -> Result<Prepared> {
    use chrono::Datelike;
    let date = chrono::NaiveDate::parse_from_str(&job.date, "%Y-%m-%d")
        .context("请选择有效的表格日期（年-月-日）")?;
    // Shift times are log-only; only Douyin's daily litre conversion uses this price.
    let price = if job.kind == "daily" && job.files.iter().any(|file| file.category == "抖音") {
        let price =
            financial_engine::source::number(&job.gas_price).context("抖音 / 92#汽油价格")?;
        anyhow::ensure!(
            price >= financial_engine::source::number("0.01")?
                && price <= financial_engine::source::number("10000")?,
            "92#汽油价格应在 0.01 至 10000 之间"
        );
        price
    } else {
        Default::default()
    };
    let day = date.day();
    let has_balance_image = job.files.iter().any(|file| file.category == "新系统卡余额");
    anyhow::ensure!(
        job.files
            .iter()
            .filter(|file| file.category == "新系统卡余额")
            .count()
            <= 1,
        "新系统卡余额请选择一张合计截图，避免重复累计"
    );
    let selected_template = path(&job.template)?
        .canonicalize()
        .context("模板不存在或无法读取")?;
    for file in &job.files {
        anyhow::ensure!(
            !path(&file.path)?
                .canonicalize()
                .is_ok_and(|source| source == selected_template),
            "模板不能与源文件使用同一个文件，未写入"
        );
    }
    for other in &job.protected_files {
        anyhow::ensure!(
            !path(other)?
                .canonicalize()
                .is_ok_and(|target| target == selected_template),
            "模板不能与其他报表或加油站的模板、源文件共用同一个文件"
        );
    }
    let directory = tempfile::tempdir()?;
    let template = directory.path().join("template.xlsx");
    std::fs::copy(&selected_template, &template)?;
    runtime::log(
        "INFO",
        &format!(
            "[{}] 开始生成{}，日期 {}，上班 {}，交班 {}",
            job.batch_id, job.kind, job.date, job.work_start, job.shift_time
        ),
    );
    for file in &job.files {
        if financial_engine::receipts::CATEGORIES.contains(&file.category.as_str()) {
            continue;
        }
        runtime::progress(
            &job.batch_id,
            &file.category,
            &file.path,
            "校验中",
            "读取源表",
        );
        match preview::table(&path(&file.path)?, "", 0) {
            Ok(page) => runtime::progress(
                &job.batch_id,
                &file.category,
                &file.path,
                "校验通过",
                format!("共 {} 行", page.total),
            ),
            Err(e) => {
                runtime::progress(
                    &job.batch_id,
                    &file.category,
                    &file.path,
                    "失败",
                    format!("{e:#}"),
                );
                return Err(e.context(file.category.clone()));
            }
        }
    }
    let req = Request {
        sources: job
            .files
            .iter()
            .map(|f| Ok((f.category.clone(), path(&f.path)?)))
            .collect::<Result<_>>()?,
        day,
        divisor: job.divisor.clone(),
        count_divisor: job.count_divisor.clone(),
        closing_balance: if has_balance_image {
            String::new()
        } else {
            job.balance.clone()
        },
    };
    let mut report = match job.kind.as_str() {
        "simple" => report::simple_for_template(&req, &template)?,
        "daily" => report::daily(&req, &template)?,
        _ => anyhow::bail!("未知报表"),
    };
    if job.kind == "daily" {
        let recognized = recognize_images(&job, false)?;
        financial_engine::receipts::apply_many(&mut report, &template, day, price, &recognized)?;
    } else {
        if let Some(amount) = daily_online_recharge(&job)? {
            let (main, _) = workbook::simple_template_sheets(&template)?;
            report
                .updates
                .get_mut(&main)
                .context("缺少简表主表数据")?
                .cells
                .insert("B12".into(), amount);
            report.notes.push("线上充值：直接复用本次日报 C73".into());
        }
        let reused_supermarket = daily_supermarket(&job)?;
        let recognized = recognize_images(&job, reused_supermarket.is_some())?;
        let amount = match reused_supermarket {
            Some(amount) => Some(amount),
            None => {
                let supermarket = recognized
                    .iter()
                    .filter(|(category, _)| category == "超市销售收入")
                    .map(|(_, data)| data.clone())
                    .collect::<Vec<_>>();
                financial_engine::receipts::supermarket_total(&supermarket)?
            }
        };
        if let Some(amount) = amount {
            let (main, _) = workbook::simple_template_sheets(&template)?;
            report
                .updates
                .get_mut(&main)
                .context("缺少简表主表数据")?
                .cells
                .insert("B11".into(), amount);
            report
                .notes
                .push("超市销售收入：已按日报金额填写 B11".into());
        }
        let balance = recognized
            .iter()
            .filter(|(category, _)| category == "新系统卡余额")
            .map(|(_, data)| data.clone())
            .collect::<Vec<_>>();
        if let Some(amount) =
            financial_engine::receipts::new_system_balance(&balance, &job.divisor)?
        {
            let (main, _) = workbook::simple_template_sheets(&template)?;
            let sheet = report.updates.get_mut(&main).context("缺少简表主表数据")?;
            sheet.cells.insert("G8".into(), amount);
            sheet.formats.insert("G8".into(), 2);
            report
                .notes
                .push("新系统卡余额：已读取期末余额合计并填写 G8".into());
        }
    }
    // Finish and validate the workbook before backing up and replacing the selected file.
    workbook::write(
        &template,
        &directory.path().join("report.xlsx"),
        &report.updates,
    )?;
    let backup = save::write_back(
        &selected_template,
        &template,
        &directory.path().join("report.xlsx"),
    )?;
    runtime::log(
        "INFO",
        &format!(
            "已保存：{}；备份：{}",
            selected_template.display(),
            backup.display()
        ),
    );
    for file in &job.files {
        if !financial_engine::receipts::CATEGORIES.contains(&file.category.as_str()) {
            runtime::progress(
                &job.batch_id,
                &file.category,
                &file.path,
                "完成",
                "已填写报表",
            );
        }
    }
    runtime::progress(
        &job.batch_id,
        if job.kind == "simple" {
            "简表模板"
        } else {
            "日报模板"
        },
        &job.template,
        "完成",
        "已保存到原模板",
    );
    let cells = report
        .updates
        .iter()
        .flat_map(|(sheet, u)| {
            u.cells.iter().filter_map(|(address, value)| {
                let value = match value {
                    Cell::Number(v) | Cell::Text(v) => v.clone(),
                    Cell::Blank => "留空".into(),
                    Cell::Formula(_) => return None,
                };
                Some(PreviewCell {
                    sheet: sheet.clone(),
                    address: address.clone(),
                    value,
                })
            })
        })
        .collect();
    let id = NEXT.fetch_add(1, Ordering::Relaxed).to_string();
    let result = Prepared {
        id: id.clone(),
        kind: job.kind.clone(),
        cells,
        notes: report.notes.clone(),
        saved_path: selected_template.to_string_lossy().into_owned(),
        backup_path: backup.to_string_lossy().into_owned(),
    };
    snapshots()
        .lock()
        .map_err(|_| anyhow::anyhow!("任务状态不可用"))?
        .insert(
            id,
            Snapshot {
                batch_id: job.batch_id.clone(),
                kind: job.kind.clone(),
                supermarket_files: supermarket_files(&job),
                recharge_files: recharge_files(&job),
                directory,
                report,
            },
        );
    Ok(result)
}
/// Local report generation and system file operations.
#[module]
pub struct Reports;
#[module]
impl Reports {
    /// Choose an Excel workbook or an optional screenshot.
    pub async fn pick_file(kind: String) -> Result<Option<String>, String> {
        let dialog = if kind == "image" {
            rfd::AsyncFileDialog::new().add_filter(
                "截图",
                &["png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"],
            )
        } else {
            rfd::AsyncFileDialog::new().add_filter(
                "Excel 表格",
                if kind == "template" {
                    &["xlsx"][..]
                } else {
                    &["xlsx", "xls", "csv"][..]
                },
            )
        };
        Ok(dialog
            .pick_file()
            .await
            .map(|f| f.path().to_string_lossy().into_owned()))
    }
    /// Calculate, back up and save the selected template; retain a preview snapshot.
    pub async fn prepare(job: Job) -> Result<Prepared, String> {
        blocking(move || {
            let category = if job.kind == "simple" {
                "简表模板"
            } else {
                "日报模板"
            };
            let template = job.template.clone();
            let batch_id = job.batch_id.clone();
            runtime::progress(&batch_id, category, &template, "处理中", "正在生成报表");
            prepare(job).inspect_err(|e| {
                runtime::progress(&batch_id, category, &template, "失败", format!("{e:#}"))
            })
        })
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| format!("{e:#}"))
    }
    /// Keep a pasted image for this application session.
    pub async fn paste_image(data: String, batch_id: String) -> Result<String, String> {
        use base64::Engine;
        let (_, encoded) = data.split_once(',').ok_or("剪贴板图片格式无效")?;
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|_| "剪贴板图片格式无效")?;
        if bytes.len() > 20 * 1024 * 1024 {
            return Err("图片超过 20 MB".into());
        }
        let mut file = tempfile::Builder::new()
            .suffix(".png")
            .tempfile()
            .map_err(|e| e.to_string())?;
        std::io::Write::write_all(&mut file, &bytes).map_err(|e| e.to_string())?;
        let path = file.path().to_string_lossy().into_owned();
        PASTED
            .get_or_init(Default::default)
            .lock()
            .map_err(|_| "图片状态不可用")?
            .entry(batch_id)
            .or_default()
            .push(file);
        Ok(path)
    }
    /// Validate an upload immediately, preserving the original file.
    pub async fn validate_file(value: String, kind: String) -> Result<String, String> {
        blocking(move || -> Result<String> {
            let file = path(&value)?
                .canonicalize()
                .context("文件不存在或无法读取")?;
            anyhow::ensure!(file.is_file(), "请选择文件");
            let ext = file
                .extension()
                .unwrap_or_default()
                .to_string_lossy()
                .to_lowercase();
            let allowed = match kind.as_str() {
                "image" => vec!["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"],
                "template" => vec!["xlsx"],
                _ => vec!["xlsx", "xls", "csv"],
            };
            anyhow::ensure!(allowed.contains(&ext.as_str()), "不支持的文件格式：{ext}");
            if kind == "image" {
                preview::image_bytes(&file)?;
            } else {
                preview::table(&file, "", 0)?;
            }
            runtime::log(
                "INFO",
                &format!(
                    "已上传：{}",
                    file.file_name().unwrap_or_default().to_string_lossy()
                ),
            );
            Ok(file.to_string_lossy().into_owned())
        })
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| format!("{e:#}"))
    }
    /// Read one page of a workbook without modifying it.
    pub async fn table_preview(
        value: String,
        sheet: String,
        offset: u32,
    ) -> Result<preview::TablePage, String> {
        blocking(move || preview::table(&path(&value)?, &sheet, offset))
            .await
            .map_err(|e| e.to_string())?
            .map_err(|e| format!("{e:#}"))
    }
    /// Decode a supported image to a preview URL.
    pub async fn image_preview(value: String) -> Result<String, String> {
        blocking(move || preview::image_data(&path(&value)?))
            .await
            .map_err(|e| e.to_string())?
            .map_err(|e| format!("{e:#}"))
    }
    /// Get the frozen output workbook for preview.
    pub fn output_path(id: String) -> Result<String, String> {
        let all = snapshots().lock().map_err(|_| "结果不可用")?;
        Ok(all
            .get(&id)
            .ok_or("结果已失效")?
            .directory
            .path()
            .join("report.xlsx")
            .to_string_lossy()
            .into_owned())
    }
    /// Read new log bytes and the latest per-file progress.
    pub fn activity(cursor: u32) -> Result<runtime::Activity, String> {
        runtime::activity(cursor).map_err(|e| e.to_string())
    }
    /// Load saved preferences with legacy environment overrides.
    pub fn preferences() -> Result<runtime::Preferences, String> {
        runtime::preferences().map_err(|e| e.to_string())
    }
    /// Persist appearance and recognition settings.
    pub fn save_preferences(settings: runtime::Preferences) -> Result<(), String> {
        runtime::save_preferences(settings).map_err(|e| e.to_string())
    }
    /// Restore fixed station profiles, without restoring daily work.
    pub fn stations() -> Result<stations::Stations, String> {
        runtime::data_dir()
            .and_then(|root| stations::load(&root))
            .map_err(|e| e.to_string())
    }
    /// Atomically save station names, prices, order and selection.
    pub fn save_stations(value: stations::Stations) -> Result<(), String> {
        runtime::data_dir()
            .and_then(|root| stations::save(&root, &value))
            .map_err(|e| e.to_string())
    }
    /// Record an application error without provider credentials.
    pub fn log_error(message: String) {
        runtime::log("ERROR", &message);
    }
    /// Protect the desktop window while a task is running.
    pub fn set_busy(busy: bool) {
        nsh_core::ui::desktop::set_close_blocked(busy);
    }
    /// Clear the preceding task progress.
    pub fn begin(batch_id: String) {
        runtime::clear_progress(&batch_id);
    }
    /// Discard only application-owned temporary files and results.
    pub fn reset(batch_id: String) {
        if let Ok(mut all) = snapshots().lock() {
            all.retain(|_, snapshot| snapshot.batch_id != batch_id);
        }
        if let Ok(mut pasted) = PASTED.get_or_init(Default::default).lock() {
            pasted.remove(&batch_id);
        }
        runtime::clear_progress(&batch_id);
        runtime::log("INFO", &format!("[{batch_id}] 已重置文件和处理结果"));
    }
    /// Check the official repository for a newer release.
    pub async fn check_update() -> Result<updater::Release, String> {
        blocking(updater::check)
            .await
            .map_err(|e| e.to_string())?
            .map_err(|e| format!("{e:#}"))
    }
    /// Download the selected release in a background thread.
    pub async fn download_update() -> Result<(), String> {
        blocking(updater::download)
            .await
            .map_err(|e| e.to_string())?
            .map_err(|e| format!("{e:#}"))
    }
    /// Cancel the current installer download.
    pub fn cancel_update() {
        updater::cancel();
    }
    /// Read installer download progress.
    pub fn update_progress() -> updater::Download {
        updater::status()
    }
    /// Launch the downloaded installer; true requests application exit.
    pub fn install_update() -> Result<bool, String> {
        updater::install()
            .map(|_| cfg!(target_os = "windows"))
            .map_err(|e| e.to_string())
    }
    /// Whether this process should perform the startup version check.
    pub fn auto_check_update() -> bool {
        std::env::var_os("FINANCIAL_DISABLE_UPDATE_CHECK").is_none()
    }
    /// Return the bundled application version.
    pub fn version() -> String {
        env!("CARGO_PKG_VERSION").into()
    }
    /// Release a prepared result after inputs change.
    pub fn discard(id: String) {
        if let Ok(mut all) = snapshots().lock() {
            all.remove(&id);
        }
    }
    /// Display a local filename, including file URLs.
    pub fn file_name(value: String) -> String {
        path(&value)
            .ok()
            .and_then(|p| p.file_name().map(|n| n.to_string_lossy().into_owned()))
            .unwrap_or(value)
    }
    /// Compare selected files after resolving file URLs and filesystem aliases.
    pub fn same_file(first: String, second: String) -> bool {
        match (
            path(&first).and_then(|p| Ok(p.canonicalize()?)),
            path(&second).and_then(|p| Ok(p.canonicalize()?)),
        ) {
            (Ok(first), Ok(second)) => first == second,
            _ => false,
        }
    }
}
#[native_module("financial/native")]
fn native(registry: &mut Registry) {
    registry.module::<Reports>();
    #[cfg(debug_assertions)]
    registry.module::<test_files::TestFiles>();
}

#[cfg(test)]
mod tests {
    use super::*;
    use calamine::Reader;
    fn isolated_fixture() -> tempfile::TempDir {
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../fixtures");
        let directory = tempfile::tempdir().unwrap();
        for entry in std::fs::read_dir(source).unwrap() {
            let entry = entry.unwrap();
            if entry.file_type().unwrap().is_file() {
                std::fs::copy(entry.path(), directory.path().join(entry.file_name())).unwrap();
            }
        }
        directory
    }
    fn job(root: &std::path::Path) -> Job {
        Job {
            batch_id: "test-snapshot".into(),
            kind: "simple".into(),
            daily_result_id: String::new(),
            template: root.join("simple.xlsx").to_string_lossy().into_owned(),
            protected_files: vec![],
            files: vec![
                ("油品时间统计", "stats.csv"),
                ("加油明细", "details.csv"),
                ("充值明细", "recharge.csv"),
            ]
            .into_iter()
            .map(|(category, name)| InputFile {
                category: category.into(),
                path: root.join(name).to_string_lossy().into_owned(),
            })
            .collect(),
            date: "2026-10-20".into(),
            work_start: "2026-10-20 07:00:00".into(),
            shift_time: "2026-10-21 07:00:00".into(),
            divisor: "3".into(),
            count_divisor: "3".into(),
            balance: "300".into(),
            gas_price: "8.23".into(),
            api_key: String::new(),
            api_base: String::new(),
            model: String::new(),
        }
    }

    fn supermarket_provider(cash: serde_json::Value) -> (String, std::thread::JoinHandle<()>) {
        receipt_provider(serde_json::json!({"现金":cash}), "班次交款")
    }

    fn receipt_provider(
        data: serde_json::Value,
        expected_prompt: &'static str,
    ) -> (String, std::thread::JoinHandle<()>) {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let server = std::thread::spawn(move || {
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
            let mut stream = loop {
                match listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        assert!(
                            std::time::Instant::now() < deadline,
                            "expected an OCR request"
                        );
                        std::thread::sleep(std::time::Duration::from_millis(2));
                    }
                    Err(error) => panic!("{error}"),
                }
            };
            stream.set_nonblocking(false).unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            let mut bytes = vec![];
            let mut chunk = [0u8; 4096];
            loop {
                let n = stream.read(&mut chunk).unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                    let length: usize = String::from_utf8_lossy(&bytes[..end])
                        .lines()
                        .find_map(|line| {
                            line.to_lowercase()
                                .strip_prefix("content-length: ")
                                .and_then(|n| n.parse().ok())
                        })
                        .unwrap();
                    if bytes.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            let raw = String::from_utf8(bytes).unwrap();
            assert!(raw.contains(expected_prompt));
            let data = data.to_string();
            let body = serde_json::json!({"candidates":[{"content":{"parts":[{"text":data}]}}]})
                .to_string();
            write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
        });
        (format!("http://{address}"), server)
    }

    fn add_supermarket(job: &mut Job, fixture: &std::path::Path) {
        job.files.push(InputFile {
            category: "超市销售收入".into(),
            path: fixture.join("receipt.png").to_string_lossy().into_owned(),
        });
        job.api_key = "test-key".into();
        job.model = "test-model".into();
    }

    fn add_balance_image(job: &mut Job, fixture: &std::path::Path) {
        job.files.push(InputFile {
            category: "新系统卡余额".into(),
            path: fixture.join("receipt.png").to_string_lossy().into_owned(),
        });
        job.api_key = "test-key".into();
        job.model = "test-model".into();
    }

    #[test]
    fn balance_image_writes_g8_instead_of_the_heading_and_overrides_manual_input() {
        let files = isolated_fixture();
        let template = files.path().join("simple.xlsx");
        let labeled = files.path().join("labeled.xlsx");
        let mut labels = financial_engine::Updates::new();
        labels
            .entry("Sheet1".into())
            .or_default()
            .cells
            .insert("G7".into(), Cell::Text("卡余额".into()));
        workbook::write(&template, &labeled, &labels).unwrap();
        std::fs::copy(labeled, &template).unwrap();
        for (data, expected) in [
            (serde_json::json!({"期末余额":"1,234.50"}), "411.5"),
            (serde_json::json!({"期末余额":0}), "0"),
        ] {
            let mut request = job(files.path());
            request.balance = "invalid manual value must be ignored".into();
            add_balance_image(&mut request, files.path());
            let mut before = calamine::open_workbook_auto(&request.template).unwrap();
            let heading = before
                .worksheet_range("Sheet1")
                .unwrap()
                .get_value((6, 6))
                .cloned();
            drop(before);
            let (base, server) = receipt_provider(data, "只读取底部统计或合计行");
            request.api_base = base;
            let result = prepare(request).unwrap();
            server.join().unwrap();
            assert_eq!(
                result
                    .cells
                    .iter()
                    .find(|cell| cell.address == "G8")
                    .unwrap()
                    .value,
                expected
            );
            assert!(!result.cells.iter().any(|cell| cell.address == "G7"));
            let mut saved = calamine::open_workbook_auto(&result.saved_path).unwrap();
            let sheet = saved.worksheet_range("Sheet1").unwrap();
            assert_eq!(sheet.get_value((7, 6)).unwrap().to_string(), expected);
            assert_eq!(sheet.get_value((6, 6)).cloned(), heading);
            Reports::discard(result.id);
        }
    }

    #[test]
    fn daily_ignores_the_simple_only_balance_image() {
        let files = isolated_fixture();
        let mut request = job(files.path());
        request.kind = "daily".into();
        request.template = files
            .path()
            .join("daily.xlsx")
            .to_string_lossy()
            .into_owned();
        request.files.push(InputFile {
            category: "油品优惠".into(),
            path: files
                .path()
                .join("discounts.csv")
                .to_string_lossy()
                .into_owned(),
        });
        request.files.push(InputFile {
            category: "新系统卡余额".into(),
            path: "/missing/unused-balance.png".into(),
        });
        let result = prepare(request).unwrap();
        assert!(!result.cells.iter().any(|cell| cell.address == "G8"));
        Reports::discard(result.id);
    }

    #[test]
    fn unused_shift_times_and_price_do_not_block_reports_but_douyin_still_needs_its_price() {
        let files = isolated_fixture();
        for kind in ["simple", "daily"] {
            let mut request = job(files.path());
            request.kind = kind.into();
            request.work_start.clear();
            request.shift_time = "log-only value".into();
            request.gas_price = "unused".into();
            if kind == "daily" {
                request.template = files
                    .path()
                    .join("daily.xlsx")
                    .to_string_lossy()
                    .into_owned();
                request.files.push(InputFile {
                    category: "油品优惠".into(),
                    path: files
                        .path()
                        .join("discounts.csv")
                        .to_string_lossy()
                        .into_owned(),
                });
            }
            let result = prepare(request.clone()).unwrap();
            Reports::discard(result.id);
            if kind == "daily" {
                request.files.push(InputFile {
                    category: "抖音".into(),
                    path: files
                        .path()
                        .join("receipt.png")
                        .to_string_lossy()
                        .into_owned(),
                });
                let before = std::fs::read(&request.template).unwrap();
                for price in ["invalid", "0", "10001"] {
                    request.gas_price = price.into();
                    assert!(
                        format!("{:#}", prepare(request.clone()).err().unwrap())
                            .contains("汽油价格")
                    );
                    assert_eq!(std::fs::read(&request.template).unwrap(), before);
                }
            }
        }
    }

    #[test]
    fn missing_or_unreadable_balance_does_not_overwrite_a_saved_workbook() {
        let files = isolated_fixture();
        let mut request = job(files.path());
        request.balance.clear();
        let mut before = calamine::open_workbook_auto(&request.template).unwrap();
        let balance = before
            .worksheet_range("Sheet1")
            .unwrap()
            .get_value((7, 6))
            .cloned();
        drop(before);
        let result = prepare(request.clone()).unwrap();
        let mut saved = calamine::open_workbook_auto(&result.saved_path).unwrap();
        assert_eq!(
            saved
                .worksheet_range("Sheet1")
                .unwrap()
                .get_value((7, 6))
                .cloned(),
            balance
        );
        Reports::discard(result.id);
        drop(saved);
        let original = std::fs::read(&request.template).unwrap();
        add_balance_image(&mut request, files.path());
        let (base, server) = receipt_provider(serde_json::json!({"期末余额":null}), "期末余额");
        request.api_base = base;
        assert!(
            prepare(request.clone())
                .err()
                .unwrap()
                .to_string()
                .contains("新系统卡余额")
        );
        server.join().unwrap();
        assert_eq!(std::fs::read(&request.template).unwrap(), original);
        add_balance_image(&mut request, files.path());
        assert!(
            prepare(request)
                .err()
                .unwrap()
                .to_string()
                .contains("一张合计截图")
        );
    }

    #[test]
    fn supermarket_cash_reaches_simple_without_a_daily_template_including_zero() {
        let files = isolated_fixture();
        let fixture = files.path().to_owned();
        for (cash, expected) in [
            (serde_json::json!("587.70"), "195.9"),
            (serde_json::json!(0), "0"),
        ] {
            let mut request = job(&fixture);
            request.batch_id = format!("supermarket-only-{expected}");
            add_supermarket(&mut request, &fixture);
            let (base, server) = supermarket_provider(cash);
            request.api_base = base;
            // Other daily receipts never enter the simple report's OCR request.
            request.files.push(InputFile {
                category: "国通1".into(),
                path: "/missing/ignored.png".into(),
            });
            let prepared = prepare(request).unwrap();
            server.join().unwrap();
            let cell = prepared
                .cells
                .iter()
                .find(|cell| cell.address == "B11")
                .unwrap();
            assert_eq!(cell.sheet, "Sheet1");
            assert_eq!(cell.value, expected);
            let mut book = calamine::open_workbook_auto(&prepared.saved_path).unwrap();
            assert!(std::path::Path::new(&prepared.backup_path).is_file());
            assert_eq!(
                book.worksheet_range_at(0)
                    .unwrap()
                    .unwrap()
                    .get_value((10, 1))
                    .unwrap()
                    .to_string(),
                expected
            );
            Reports::discard(prepared.id);
        }
    }

    #[test]
    fn simple_reuses_daily_online_recharge_and_checks_its_station_and_source() {
        let files = isolated_fixture();
        std::fs::write(
            files.path().join("recharge.csv"),
            "原余额,充值金额,充值赠送,付款方式\n100,21844,240,微信收款\n",
        )
        .unwrap();
        let mut daily = job(files.path());
        daily.batch_id = "online-recharge-reuse".into();
        daily.kind = "daily".into();
        daily.template = files
            .path()
            .join("daily.xlsx")
            .to_string_lossy()
            .into_owned();
        daily.files.push(InputFile {
            category: "油品优惠".into(),
            path: files
                .path()
                .join("discounts.csv")
                .to_string_lossy()
                .into_owned(),
        });
        let result = prepare(daily.clone()).unwrap();
        assert!(daily_online_recharge(&daily).unwrap().is_none());
        let mut simple = daily;
        simple.kind = "simple".into();
        simple.template = files
            .path()
            .join("simple.xlsx")
            .to_string_lossy()
            .into_owned();
        simple.daily_result_id = result.id.clone();
        simple.divisor = "6".into();
        let reused = prepare(simple.clone()).unwrap();
        assert_eq!(
            reused
                .cells
                .iter()
                .find(|cell| cell.address == "B12")
                .unwrap()
                .value,
            "7361.33"
        );
        Reports::discard(reused.id);
        let mut wrong = simple.clone();
        wrong.batch_id = "different-station".into();
        assert!(
            daily_online_recharge(&wrong)
                .unwrap_err()
                .to_string()
                .contains("当前加油站")
        );
        let mut wrong = simple.clone();
        wrong
            .files
            .iter_mut()
            .find(|file| file.category == "充值明细")
            .unwrap()
            .path
            .push_str(".changed");
        assert!(
            daily_online_recharge(&wrong)
                .unwrap_err()
                .to_string()
                .contains("充值明细已变化")
        );
        Reports::discard(result.id);
        assert!(
            daily_online_recharge(&simple)
                .unwrap_err()
                .to_string()
                .contains("已失效")
        );
        simple.daily_result_id.clear();
        simple.divisor = "3".into();
        let standalone = prepare(simple).unwrap();
        assert_eq!(
            standalone
                .cells
                .iter()
                .find(|cell| cell.address == "B12")
                .unwrap()
                .value,
            "7361.33"
        );
        Reports::discard(standalone.id);
    }

    #[test]
    fn simple_reuses_the_daily_supermarket_value_without_another_request_or_division() {
        let files = isolated_fixture();
        let fixture = files.path().to_owned();
        let mut daily = job(&fixture);
        daily.batch_id = "supermarket-daily-reuse".into();
        daily.kind = "daily".into();
        daily.template = fixture.join("daily.xlsx").to_string_lossy().into_owned();
        daily.files.push(InputFile {
            category: "油品优惠".into(),
            path: fixture.join("discounts.csv").to_string_lossy().into_owned(),
        });
        add_supermarket(&mut daily, &fixture);
        let (base, server) = supermarket_provider(serde_json::json!("587.70"));
        daily.api_base = base;
        let result = prepare(daily.clone()).unwrap();
        server.join().unwrap(); // exactly one provider request; it is now offline
        assert_eq!(
            result
                .cells
                .iter()
                .find(|cell| cell.address == "H71")
                .unwrap()
                .value,
            "195.9"
        );
        let mut simple = daily;
        simple.kind = "simple".into();
        simple.template = fixture.join("simple.xlsx").to_string_lossy().into_owned();
        simple.daily_result_id = result.id.clone();
        simple.api_key.clear(); // reuse works without a second OCR request
        simple.divisor = "6".into(); // the already-rounded daily amount must stay the same
        for _ in 0..2 {
            let result = prepare(simple.clone()).unwrap();
            assert_eq!(
                result
                    .cells
                    .iter()
                    .find(|cell| cell.address == "B11")
                    .unwrap()
                    .value,
                "195.9"
            );
            Reports::discard(result.id);
        }
        let mut with_balance = simple.clone();
        add_balance_image(&mut with_balance, &fixture);
        let (base, server) = receipt_provider(
            serde_json::json!({"期末余额":"1234.50"}),
            "只读取底部统计或合计行",
        );
        with_balance.api_base = base;
        let combined = prepare(with_balance).unwrap();
        server.join().unwrap();
        for (address, expected) in [("B11", "195.9"), ("G8", "205.75")] {
            assert_eq!(
                combined
                    .cells
                    .iter()
                    .find(|cell| cell.address == address)
                    .unwrap()
                    .value,
                expected
            );
        }
        Reports::discard(combined.id);
        let mut wrong = simple.clone();
        wrong.batch_id = "other-station".into();
        assert!(
            prepare(wrong)
                .err()
                .unwrap()
                .to_string()
                .contains("当前加油站")
        );
        let mut wrong = simple.clone();
        wrong
            .files
            .iter_mut()
            .find(|file| file.category == "超市销售收入")
            .unwrap()
            .path
            .push_str(".changed");
        assert!(
            prepare(wrong)
                .err()
                .unwrap()
                .to_string()
                .contains("截图已变化")
        );
        Reports::discard(result.id);
        assert!(
            prepare(simple)
                .err()
                .unwrap()
                .to_string()
                .contains("日报结果已失效")
        );
    }

    #[test]
    fn missing_supermarket_preserves_b11_but_unreadable_cash_fails() {
        let files = isolated_fixture();
        let fixture = files.path().to_owned();
        let temp = tempfile::tempdir().unwrap();
        let template = temp.path().join("simple.xlsx");
        let mut update = financial_engine::SheetUpdate::default();
        update
            .cells
            .insert("B11".into(), Cell::Number("123".into()));
        workbook::write(
            &fixture.join("simple.xlsx"),
            &template,
            &BTreeMap::from([("Sheet1".into(), update)]),
        )
        .unwrap();
        let mut request = job(&fixture);
        request.batch_id = "supermarket-preserve".into();
        request.template = template.to_string_lossy().into_owned();
        let result = prepare(request.clone()).unwrap();
        assert!(!result.cells.iter().any(|cell| cell.address == "B11"));
        let mut book = calamine::open_workbook_auto(&result.saved_path).unwrap();
        assert_eq!(
            book.worksheet_range_at(0)
                .unwrap()
                .unwrap()
                .get_value((10, 1))
                .unwrap()
                .to_string(),
            "123"
        );
        Reports::discard(result.id);
        let saved = std::fs::read(&template).unwrap();
        add_supermarket(&mut request, &fixture);
        let (base, server) = supermarket_provider(serde_json::Value::Null);
        request.api_base = base;
        let error = prepare(request).err().unwrap();
        assert!(format!("{error:#}").contains("未识别"));
        assert_eq!(std::fs::read(&template).unwrap(), saved);
        server.join().unwrap();
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn finder_file_reference_resolves_before_filesystem_validation() {
        use objc2_foundation::{NSString, NSURL};
        let tmp = tempfile::tempdir().unwrap();
        let file = tmp.path().join("充值 明细%20.csv");
        std::fs::write(&file, "金额\n123").unwrap();
        let ordinary = url::Url::from_file_path(&file).unwrap();
        let reference = NSURL::URLWithString(&NSString::from_str(ordinary.as_str()))
            .unwrap()
            .fileReferenceURL()
            .unwrap()
            .absoluteString()
            .unwrap()
            .to_string();
        assert!(reference.contains("/.file/id="));
        // This is the exact OS error the unconverted clipboard path produced.
        let raw_path = url::Url::parse(&reference).unwrap().to_file_path().unwrap();
        assert_eq!(
            raw_path.canonicalize().unwrap_err().raw_os_error(),
            Some(20)
        );
        let resolved = path(&reference).unwrap().canonicalize().unwrap();
        assert_eq!(resolved, file.canonicalize().unwrap());
        assert_eq!(std::fs::read_to_string(resolved).unwrap(), "金额\n123");
        assert_eq!(path(ordinary.as_str()).unwrap(), file);
    }

    #[test]
    fn resetting_one_batch_preserves_other_progress_outputs_and_pasted_files() {
        let first_files = isolated_fixture();
        let second_files = isolated_fixture();
        let mut first = job(first_files.path());
        first.batch_id = "isolation-first".into();
        let mut second = job(second_files.path());
        second.batch_id = "isolation-second".into();
        second.balance = "600".into();
        let (first, second) = std::thread::scope(|scope| {
            let a = scope.spawn(|| prepare(first).unwrap());
            let b = scope.spawn(|| prepare(second).unwrap());
            (a.join().unwrap(), b.join().unwrap())
        });
        let first_image = tempfile::NamedTempFile::new().unwrap();
        let first_path = first_image.path().to_owned();
        let second_image = tempfile::NamedTempFile::new().unwrap();
        let second_path = second_image.path().to_owned();
        {
            let mut pasted = PASTED.get_or_init(Default::default).lock().unwrap();
            pasted.insert("isolation-first".into(), vec![first_image]);
            pasted.insert("isolation-second".into(), vec![second_image]);
        }
        Reports::reset("isolation-first".into());
        assert!(std::path::Path::new(&first.saved_path).is_file());
        assert!(Reports::output_path(first.id).is_err());
        assert!(!first_path.exists());
        assert!(second_path.exists());
        let activity = runtime::activity(0).unwrap();
        assert!(
            !activity
                .progress
                .iter()
                .any(|p| p.batch_id == "isolation-first")
        );
        assert!(
            activity
                .progress
                .iter()
                .any(|p| p.batch_id == "isolation-second")
        );
        let mut book = calamine::open_workbook_auto(&second.saved_path).unwrap();
        assert_eq!(
            book.worksheet_range("Sheet1")
                .unwrap()
                .get_value((7, 6))
                .unwrap()
                .to_string(),
            "200"
        );
        Reports::reset("isolation-second".into());
        assert!(!second_path.exists());
    }

    #[test]
    fn public_job_saves_original_template_with_backup_and_keeps_a_frozen_preview() {
        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../fixtures");
        let tmp = tempfile::tempdir().unwrap();
        for name in ["simple.xlsx", "stats.csv", "details.csv", "recharge.csv"] {
            std::fs::copy(fixture.join(name), tmp.path().join(name)).unwrap();
        }
        let mut invalid = job(tmp.path());
        invalid.date = "2026-02-30".into();
        assert!(prepare(invalid).is_err());
        let mut invalid = job(tmp.path());
        invalid.divisor = "0".into();
        assert!(prepare(invalid).is_err());
        let mut invalid = job(tmp.path());
        invalid.count_divisor = "invalid".into();
        assert!(prepare(invalid).is_err());
        let before = std::fs::read(tmp.path().join("simple.xlsx")).unwrap();
        let source_before = std::fs::read(tmp.path().join("recharge.csv")).unwrap();
        let result = prepare(job(tmp.path())).unwrap();
        assert_ne!(
            std::fs::read(tmp.path().join("simple.xlsx")).unwrap(),
            before
        );
        assert_eq!(std::fs::read(&result.backup_path).unwrap(), before);
        assert_eq!(
            std::fs::read(tmp.path().join("recharge.csv")).unwrap(),
            source_before
        );
        let saved = std::fs::read(&result.saved_path).unwrap();
        let repeated = prepare(job(tmp.path())).unwrap();
        assert_eq!(std::fs::read(&repeated.backup_path).unwrap(), saved);
        assert_ne!(repeated.backup_path, result.backup_path);
        std::fs::write(tmp.path().join("recharge.csv"), "changed after calculation").unwrap();
        std::fs::write(tmp.path().join("simple.xlsx"), "changed after calculation").unwrap();
        let output = Reports::output_path(result.id.clone()).unwrap();
        let mut book = calamine::open_workbook_auto(&output).unwrap();
        let range = book.worksheet_range("Sheet1").unwrap();
        assert_eq!(range.get_value((8, 3)).unwrap().to_string(), "510");
        assert_eq!(range.get_value((7, 6)).unwrap().to_string(), "100");
        assert_eq!(range.get_value((9, 1)).unwrap().to_string(), "保留");
        Reports::discard(result.id.clone());
        assert!(Reports::output_path(result.id).is_err());
    }

    #[test]
    fn readonly_daily_and_simple_workbooks_save_and_clean_up_their_previews() {
        for kind in ["daily", "simple"] {
            let files = isolated_fixture();
            let mut request = job(files.path());
            request.batch_id = format!("readonly-{kind}");
            request.kind = kind.into();
            request.template = files
                .path()
                .join(format!("{kind}.xlsx"))
                .to_string_lossy()
                .into_owned();
            if kind == "daily" {
                request.files.push(InputFile {
                    category: "油品优惠".into(),
                    path: files
                        .path()
                        .join("discounts.csv")
                        .to_string_lossy()
                        .into_owned(),
                });
            }
            let original = std::fs::read(&request.template).unwrap();
            let mut permissions = std::fs::metadata(&request.template).unwrap().permissions();
            permissions.set_readonly(true);
            std::fs::set_permissions(&request.template, permissions).unwrap();
            let result = prepare(request).unwrap();
            assert_eq!(std::fs::read(&result.backup_path).unwrap(), original);
            assert_ne!(std::fs::read(&result.saved_path).unwrap(), original);
            assert!(
                !std::fs::metadata(&result.saved_path)
                    .unwrap()
                    .permissions()
                    .readonly()
            );
            let preview = PathBuf::from(Reports::output_path(result.id.clone()).unwrap());
            let directory = preview.parent().unwrap().to_owned();
            Reports::discard(result.id);
            assert!(!directory.exists());
        }
    }

    #[test]
    fn write_back_rejects_source_aliases_and_reused_template_targets() {
        let files = isolated_fixture();
        let mut request = job(files.path());
        let original = std::fs::read(&request.template).unwrap();
        request.files[0].path = request.template.clone();
        assert!(
            prepare(request)
                .err()
                .unwrap()
                .to_string()
                .contains("源文件")
        );
        let mut request = job(files.path());
        request.protected_files.push(
            url::Url::from_file_path(&request.template)
                .unwrap()
                .to_string(),
        );
        assert!(prepare(request).err().unwrap().to_string().contains("共用"));
        assert_eq!(
            std::fs::read(files.path().join("simple.xlsx")).unwrap(),
            original
        );
    }
}
