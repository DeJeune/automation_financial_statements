//! Release checks and cancellable installer downloads. No shell interpolation.
use anyhow::{Context, Result, ensure};
use nsh_core::ui::prelude::*;
use serde_json::Value;
use std::{
    io::{Read, Write},
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
const API: &str =
    "https://api.github.com/repos/DeJeune/automation_financial_statements/releases/latest";
const PREFIX: &str =
    "https://github.com/DeJeune/automation_financial_statements/releases/download/";
#[derive(Clone, JsObject)]
pub struct Release {
    pub version: String,
    pub notes: String,
    pub available: bool,
    pub downloadable: bool,
}
#[derive(Clone, Default, JsObject)]
pub struct Download {
    pub received: String,
    pub total: String,
    pub ready: bool,
}
struct Asset {
    url: String,
    name: String,
    size: u64,
}
static ASSET: Mutex<Option<Asset>> = Mutex::new(None);
static DOWNLOAD: Mutex<Download> = Mutex::new(Download {
    received: String::new(),
    total: String::new(),
    ready: false,
});
static INSTALLER: Mutex<Option<std::path::PathBuf>> = Mutex::new(None);
static CANCELLED: AtomicBool = AtomicBool::new(false);
static DOWNLOADING: AtomicBool = AtomicBool::new(false);
fn version(v: &str) -> Result<Vec<u32>> {
    v.trim_start_matches(['v', 'V'])
        .split('.')
        .map(|s| s.parse().context("版本号无效"))
        .collect()
}
fn client() -> Result<reqwest::blocking::Client> {
    Ok(reqwest::blocking::Client::builder()
        .user_agent("FinancialAutomation-Updater")
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(30))
        .https_only(true)
        .build()?)
}
fn compatible(name: &str, os: &str) -> bool {
    match os {
        "windows" => name.starts_with("Financial_Automation_Setup_") && name.ends_with(".exe"),
        "macos" => {
            name.starts_with("FinancialAutomation")
                && (name.ends_with("-macOS.zip") || name.ends_with(".dmg"))
        }
        _ => false,
    }
}
fn parse_release(data: &Value, os: &str) -> Result<(Release, Option<Asset>)> {
    let tag = data["tag_name"].as_str().context("更新响应缺少版本号")?;
    let available = version(tag)? > version(env!("CARGO_PKG_VERSION"))?;
    let asset = data["assets"]
        .as_array()
        .into_iter()
        .flatten()
        .find_map(|a| {
            let name = a["name"].as_str()?;
            let url = a["browser_download_url"].as_str()?;
            (compatible(name, os) && !name.contains(['/', '\\']) && url.starts_with(PREFIX)).then(
                || Asset {
                    name: name.into(),
                    url: url.into(),
                    size: a["size"].as_u64().unwrap_or(0),
                },
            )
        });
    Ok((
        Release {
            version: tag.into(),
            notes: data["body"].as_str().unwrap_or_default().into(),
            available,
            downloadable: asset.is_some(),
        },
        asset,
    ))
}
pub fn check() -> Result<Release> {
    let response = client()?.get(API).send().context("无法连接更新服务器")?;
    if response.status().as_u16() == 404 {
        return Ok(Release {
            version: env!("CARGO_PKG_VERSION").into(),
            notes: String::new(),
            available: false,
            downloadable: false,
        });
    }
    let data: Value = response.error_for_status()?.json()?;
    let (release, asset) = parse_release(&data, std::env::consts::OS)?;
    *ASSET
        .lock()
        .map_err(|_| anyhow::anyhow!("更新状态不可用"))? =
        if release.available { asset } else { None };
    crate::runtime::log("INFO", &format!("检查更新：{}", release.version));
    Ok(release)
}
pub fn download() -> Result<()> {
    ensure!(!DOWNLOADING.swap(true, Ordering::SeqCst), "更新正在下载");
    struct Guard;
    impl Drop for Guard {
        fn drop(&mut self) {
            DOWNLOADING.store(false, Ordering::SeqCst);
        }
    }
    let _guard = Guard;
    CANCELLED.store(false, Ordering::SeqCst);
    *INSTALLER.lock().unwrap() = None;
    *DOWNLOAD.lock().unwrap() = Download::default();
    let (url, name, size) = {
        let lock = ASSET.lock().unwrap();
        let a = lock.as_ref().context("请先检查更新")?;
        (a.url.clone(), a.name.clone(), a.size)
    };
    let mut response = client()?.get(url).send()?.error_for_status()?;
    let total = response.content_length().unwrap_or(size);
    ensure!(total <= 1024 * 1024 * 1024, "更新文件过大");
    let root = crate::runtime::data_dir()?.join("updates");
    std::fs::create_dir_all(&root)?;
    let mut file = tempfile::NamedTempFile::new_in(&root)?;
    let mut received = 0u64;
    let mut buffer = [0u8; 65536];
    loop {
        ensure!(!CANCELLED.load(Ordering::SeqCst), "已取消下载");
        let count = response.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        received += count as u64;
        ensure!(received <= 1024 * 1024 * 1024, "更新文件过大");
        file.write_all(&buffer[..count])?;
        *DOWNLOAD.lock().unwrap() = Download {
            received: received.to_string(),
            total: total.to_string(),
            ready: false,
        };
    }
    ensure!(size == 0 || received == size, "更新文件不完整");
    ensure!(total == 0 || received == total, "更新文件不完整");
    ensure!(!CANCELLED.load(Ordering::SeqCst), "已取消下载");
    let path = root.join(name);
    file.persist(&path)?;
    *INSTALLER.lock().unwrap() = Some(path);
    DOWNLOAD.lock().unwrap().ready = true;
    crate::runtime::log("INFO", "更新下载完成");
    Ok(())
}
pub fn cancel() {
    CANCELLED.store(true, Ordering::SeqCst);
}
pub fn status() -> Download {
    DOWNLOAD.lock().unwrap().clone()
}
pub fn install() -> Result<()> {
    let path = INSTALLER.lock().unwrap().clone().context("请先下载更新")?;
    ensure!(path.is_file(), "更新文件不存在");
    #[cfg(target_os = "windows")]
    std::process::Command::new(&path).spawn()?;
    #[cfg(not(target_os = "windows"))]
    open::that_detached(&path)?;
    crate::runtime::log("INFO", "已打开更新安装包");
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn version_and_asset_selection() {
        let value = serde_json::json!({"tag_name":"v2.1.0","assets":[{"name":"Financial_Automation_Setup_v2.1.0.exe","browser_download_url":format!("{PREFIX}v2.1.0/setup.exe"),"size":15}]});
        let (r, a) = parse_release(&value, "windows").unwrap();
        assert!(r.available && r.downloadable);
        assert_eq!(a.unwrap().size, 15);
        assert!(!parse_release(&value, "macos").unwrap().0.downloadable);
        assert!(version("v1.0.6").unwrap() < version("2.0.0").unwrap());
        let bad = serde_json::json!({"tag_name":"v2.1.0","assets":[{"name":"Financial_Automation_Setup_v2.1.0.exe","browser_download_url":"https://untrusted.invalid/file"}]});
        assert!(!parse_release(&bad, "windows").unwrap().0.downloadable);
    }
}
