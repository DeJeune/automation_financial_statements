//! Persistent preferences, bounded logs and progress shared by the UI and workers.
use anyhow::{Context, Result};
use chrono::Local;
use nsh_core::ui::prelude::*;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    io::{Read, Seek, Write},
    path::PathBuf,
    sync::{Mutex, OnceLock},
};

#[derive(Clone, Default, JsObject)]
pub struct Progress {
    pub batch_id: String,
    pub category: String,
    pub path: String,
    pub status: String,
    pub detail: String,
}
#[derive(Clone, JsObject)]
pub struct Activity {
    pub logs: String,
    pub cursor: u32,
    pub progress: Vec<Progress>,
}
#[derive(Clone, Serialize, Deserialize, JsObject)]
#[serde(default)]
pub struct Preferences {
    pub theme: String,
    pub api_key: String,
    pub api_base: String,
    pub model: String,
}
impl Default for Preferences {
    fn default() -> Self {
        Self {
            theme: "light".into(),
            api_key: String::new(),
            api_base: "https://generativelanguage.googleapis.com".into(),
            model: "gemini-2.0-flash".into(),
        }
    }
}
static PROGRESS: OnceLock<Mutex<BTreeMap<String, Progress>>> = OnceLock::new();
static LOG_LOCK: Mutex<()> = Mutex::new(());
const MAX_LOG: u64 = 5 * 1024 * 1024;
pub fn data_dir() -> Result<PathBuf> {
    // An isolated path also lets tests avoid touching the user's configuration.
    let base = if let Some(root) = std::env::var_os("FINANCIAL_DATA_DIR") {
        PathBuf::from(root)
    } else {
        directories::BaseDirs::new()
            .context("无法确定用户数据目录")?
            .data_local_dir()
            .join("Financial Automation")
    };
    std::fs::create_dir_all(&base)?;
    Ok(base)
}
fn log_path() -> Result<PathBuf> {
    let dir = data_dir()?.join("logs");
    std::fs::create_dir_all(&dir)?;
    Ok(dir.join("app.log"))
}
pub fn log(level: &str, message: &str) {
    let Ok(_lock) = LOG_LOCK.lock() else { return };
    let Ok(path) = log_path() else { return };
    if std::fs::metadata(&path).is_ok_and(|m| m.len() > MAX_LOG) {
        let _ = std::fs::rename(&path, path.with_extension("previous.log"));
    }
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = writeln!(
            file,
            "{} | {level} | {}",
            Local::now().format("%Y-%m-%d %H:%M:%S"),
            message.replace('\r', "")
        );
    }
}
pub fn progress(
    batch_id: &str,
    category: &str,
    path: &str,
    status: &str,
    detail: impl Into<String>,
) {
    let detail = detail.into();
    log(
        if status == "失败" { "ERROR" } else { "INFO" },
        &format!("[{batch_id}] {category} · {status} · {detail}"),
    );
    if let Ok(mut values) = PROGRESS.get_or_init(Default::default).lock() {
        values.insert(
            format!("{batch_id}\n{category}\n{path}"),
            Progress {
                batch_id: batch_id.into(),
                category: category.into(),
                path: path.into(),
                status: status.into(),
                detail,
            },
        );
    }
}
pub fn clear_progress(batch_id: &str) {
    if let Ok(mut values) = PROGRESS.get_or_init(Default::default).lock() {
        values.retain(|_, value| value.batch_id != batch_id);
    }
}
pub fn activity(cursor: u32) -> Result<Activity> {
    let _lock = LOG_LOCK.lock().map_err(|_| anyhow::anyhow!("日志不可用"))?;
    let path = log_path()?;
    let mut logs = String::new();
    let mut end = 0;
    if path.exists() {
        let mut file = std::fs::File::open(path)?;
        let len = file.metadata()?.len();
        let start = if u64::from(cursor) > len {
            0
        } else {
            u64::from(cursor)
        };
        file.seek(std::io::SeekFrom::Start(start))?;
        file.read_to_string(&mut logs)?;
        end = len as u32;
    }
    let progress = PROGRESS
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| anyhow::anyhow!("处理状态不可用"))?
        .values()
        .cloned()
        .collect();
    Ok(Activity {
        logs,
        cursor: end,
        progress,
    })
}
fn load_at(
    root: &std::path::Path,
    env_files: &[PathBuf],
    system: impl Fn(&str) -> Option<String>,
) -> Result<Preferences> {
    let path = root.join("settings.json");
    let mut settings = if path.exists() {
        serde_json::from_slice(&std::fs::read(path)?).context("配置文件损坏")?
    } else {
        Preferences::default()
    };
    let mut env = BTreeMap::new();
    if let Some(file) = env_files.iter().find(|p| p.is_file()) {
        for item in dotenvy::from_path_iter(file)? {
            let (k, v) = item?;
            env.insert(k, v);
        }
    }
    for (name, target) in [
        ("GEMINI_API_KEY", &mut settings.api_key),
        ("GEMINI_BASE_URL", &mut settings.api_base),
        ("GEMINI_MODEL", &mut settings.model),
    ] {
        if let Some(value) = system(name).or_else(|| env.get(name).cloned()) {
            *target = value;
        }
    }
    Ok(settings)
}
pub fn preferences() -> Result<Preferences> {
    let root = data_dir()?;
    let exe = std::env::current_exe()?
        .parent()
        .context("安装目录不可用")?
        .to_owned();
    let result = load_at(
        &root,
        &[
            std::env::current_dir()?.join(".env"),
            root.join(".env"),
            exe.join(".env"),
            exe.join("config/.env"),
        ],
        |key| std::env::var(key).ok(),
    );
    log("INFO", "应用已启动");
    result
}
pub fn save_preferences(settings: Preferences) -> Result<()> {
    anyhow::ensure!(
        matches!(settings.theme.as_str(), "light" | "dark"),
        "未知主题"
    );
    let root = data_dir()?;
    let mut tmp = tempfile::NamedTempFile::new_in(&root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tmp.as_file()
            .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    tmp.write_all(&serde_json::to_vec_pretty(&settings)?)?;
    tmp.persist(root.join("settings.json"))?;
    log("INFO", "设置已保存");
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn saved_preferences_and_legacy_environment_priority() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join("settings.json"),
            r#"{"theme":"dark","api_key":"saved","model":"saved-model"}"#,
        )
        .unwrap();
        let env = dir.path().join(".env");
        std::fs::write(&env, "GEMINI_API_KEY=legacy\nGEMINI_MODEL=legacy-model\n").unwrap();
        let p = load_at(dir.path(), &[env], |key| {
            (key == "GEMINI_API_KEY").then(|| "system".into())
        })
        .unwrap();
        assert_eq!(p.theme, "dark");
        assert_eq!(p.api_key, "system");
        assert_eq!(p.model, "legacy-model");
    }
}
