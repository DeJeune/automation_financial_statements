//! Native desktop boundary. All workbook work executes off the UI thread.
mod preview;
mod recognition;
mod runtime;
mod stations;
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
    pub kind: String,
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
}
struct Snapshot {
    batch_id: String,
    directory: tempfile::TempDir,
    report: Report,
    protected: Vec<PathBuf>,
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
fn prepare(job: Job) -> Result<Prepared> {
    use chrono::Datelike;
    let date = chrono::NaiveDate::parse_from_str(&job.date, "%Y-%m-%d")
        .context("请选择有效的表格日期（年-月-日）")?;
    for time in [&job.work_start, &job.shift_time] {
        chrono::NaiveDateTime::parse_from_str(time, "%Y-%m-%d %H:%M:%S")
            .context("上班和交班时间格式应为 年-月-日 时:分:秒")?;
    }
    let price = financial_engine::source::number(&job.gas_price)?;
    anyhow::ensure!(
        price >= financial_engine::source::number("0.01")?
            && price <= financial_engine::source::number("10000")?,
        "92#汽油价格应在 0.01 至 10000 之间"
    );
    let day = date.day();
    let template = path(&job.template)?;
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
        divisor: job.divisor,
        count_divisor: job.count_divisor,
        closing_balance: job.balance,
    };
    let mut report = match job.kind.as_str() {
        "simple" => report::simple(&req)?,
        "daily" => report::daily(&req, &template)?,
        _ => anyhow::bail!("未知报表"),
    };
    if job.kind == "daily" {
        let mut recognized = Vec::new();
        for file in &job.files {
            if !financial_engine::receipts::CATEGORIES.contains(&file.category.as_str()) {
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
        financial_engine::receipts::apply_many(&mut report, &template, day, price, &recognized)?;
    }
    if job.kind == "simple" {
        workbook::validate_simple_template(&template)?;
    }
    let protected = std::iter::once(&template)
        .chain(req.sources.values())
        .filter_map(|p| p.canonicalize().ok())
        .collect();
    let directory = tempfile::tempdir()?;
    let frozen = directory.path().join("template.xlsx");
    std::fs::copy(template, &frozen)?;
    // Validate the complete write, including the user's template, before showing success.
    workbook::write(
        &frozen,
        &directory.path().join("report.xlsx"),
        &report.updates,
    )?;
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
        "可导出",
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
        kind: job.kind,
        cells,
        notes: report.notes.clone(),
    };
    snapshots()
        .lock()
        .map_err(|_| anyhow::anyhow!("任务状态不可用"))?
        .insert(
            id,
            Snapshot {
                batch_id: job.batch_id,
                directory,
                report,
                protected,
            },
        );
    Ok(result)
}
fn write_snapshot(id: &str, dest: &std::path::Path) -> Result<()> {
    let locked = snapshots()
        .lock()
        .map_err(|_| anyhow::anyhow!("任务状态不可用"))?;
    let snapshot = locked.get(id).context("结果已失效，请重新计算")?;
    if dest
        .canonicalize()
        .is_ok_and(|p| snapshot.protected.contains(&p))
    {
        anyhow::bail!("不能覆盖原模板或源文件，请另选导出位置");
    }
    workbook::write(
        &snapshot.directory.path().join("template.xlsx"),
        dest,
        &snapshot.report.updates,
    )
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
    /// Validate inputs and prepare an immutable report snapshot.
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
    /// Save a prepared report through the system save dialog.
    pub async fn export(id: String, kind: String) -> Result<Option<String>, String> {
        let name = if kind == "simple" {
            "简表.xlsx"
        } else {
            "日报.xlsx"
        };
        let Some(file) = rfd::AsyncFileDialog::new()
            .add_filter("Excel 工作簿", &["xlsx"])
            .set_file_name(name)
            .save_file()
            .await
        else {
            return Ok(None);
        };
        let dest = file.path().to_path_buf();
        let shown = dest.to_string_lossy().into_owned();
        blocking(move || write_snapshot(&id, &dest))
            .await
            .map_err(|e| e.to_string())?
            .map_err(|e| format!("{e:#}"))?;
        runtime::log("INFO", &format!("已导出：{shown}"));
        Ok(Some(shown))
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
}
#[native_module("financial/native")]
fn native(registry: &mut Registry) {
    registry.module::<Reports>();
}

#[cfg(test)]
mod tests {
    use super::*;
    use calamine::Reader;
    fn job(root: &std::path::Path) -> Job {
        Job {
            batch_id: "test-snapshot".into(),
            kind: "simple".into(),
            template: root.join("simple.xlsx").to_string_lossy().into_owned(),
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
        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../fixtures");
        let mut first = job(&fixture);
        first.batch_id = "isolation-first".into();
        let mut second = job(&fixture);
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
        let destination = tempfile::tempdir().unwrap();
        let output = destination.path().join("export.xlsx");
        write_snapshot(&second.id, &output).unwrap();
        let mut book = calamine::open_workbook_auto(&output).unwrap();
        assert_eq!(
            book.worksheet_range("Sheet1")
                .unwrap()
                .get_value((6, 6))
                .unwrap()
                .to_string(),
            "200"
        );
        Reports::reset("isolation-second".into());
        assert!(!second_path.exists());
    }

    #[test]
    fn public_job_validates_dates_and_exports_an_immutable_snapshot() {
        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../fixtures");
        let tmp = tempfile::tempdir().unwrap();
        for name in ["simple.xlsx", "stats.csv", "details.csv", "recharge.csv"] {
            std::fs::copy(fixture.join(name), tmp.path().join(name)).unwrap();
        }
        let mut invalid = job(tmp.path());
        invalid.date = "2026-02-30".into();
        assert!(prepare(invalid).is_err());
        let mut invalid = job(tmp.path());
        invalid.shift_time = "25:00".into();
        assert!(prepare(invalid).is_err());
        let mut invalid = job(tmp.path());
        invalid.gas_price = "0".into();
        assert!(prepare(invalid).is_err());
        let result = prepare(job(tmp.path())).unwrap();
        assert!(write_snapshot(&result.id, &tmp.path().join("simple.xlsx")).is_err());
        std::fs::write(tmp.path().join("recharge.csv"), "changed after calculation").unwrap();
        std::fs::write(tmp.path().join("simple.xlsx"), "changed after calculation").unwrap();
        let output = tmp.path().join("export.xlsx");
        write_snapshot(&result.id, &output).unwrap();
        let mut book = calamine::open_workbook_auto(&output).unwrap();
        let range = book.worksheet_range("Sheet1").unwrap();
        assert_eq!(range.get_value((8, 3)).unwrap().to_string(), "510");
        assert_eq!(range.get_value((6, 6)).unwrap().to_string(), "100");
        assert_eq!(range.get_value((9, 1)).unwrap().to_string(), "保留");
        Reports::discard(result.id.clone());
        assert!(write_snapshot(&result.id, &output).is_err());
    }
}
