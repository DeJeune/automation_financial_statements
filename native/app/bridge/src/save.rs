//! Commit a complete report to its selected template, keeping a recoverable copy.
use anyhow::{Context, Result, ensure};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

pub fn write_back(template: &Path, frozen: &Path, report: &Path) -> Result<PathBuf> {
    let original = fs::read(frozen)?;
    ensure!(
        fs::read(template)? == original,
        "处理期间模板已被修改，请重新计算，未覆盖文件"
    );
    let permissions = fs::metadata(template)?.permissions();
    ensure!(
        !permissions.readonly(),
        "模板为只读文件，请取消只读后重新计算"
    );
    let parent = template.parent().context("模板目录不可用")?;
    let backup_dir = parent.join("报表备份");
    fs::create_dir_all(&backup_dir).context("无法创建模板备份目录，未覆盖文件")?;
    let prefix = format!(
        "{}-{}-",
        template.file_stem().unwrap_or_default().to_string_lossy(),
        chrono::Local::now().format("%Y%m%d-%H%M%S")
    );
    let mut backup = tempfile::Builder::new()
        .prefix(&prefix)
        .suffix(".xlsx")
        .tempfile_in(&backup_dir)?;
    backup.write_all(&original)?;
    backup.as_file_mut().sync_all()?;
    let (_, backup_path) = backup.keep().map_err(|e| e.error)?;

    let mut complete = tempfile::NamedTempFile::new_in(parent)?;
    std::io::copy(&mut fs::File::open(report)?, complete.as_file_mut())?;
    complete.as_file().set_permissions(permissions)?;
    complete.as_file_mut().sync_all()?;
    ensure!(
        fs::read(template)? == original,
        "保存前模板已被修改，请重新计算，未覆盖文件"
    );
    complete
        .persist(template)
        .map_err(|e| e.error)
        .with_context(|| {
            format!(
                "无法保存 {}，请关闭 Excel/WPS 后重新计算；原文件保持不变",
                template.display()
            )
        })?;
    Ok(backup_path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_back_keeps_each_original_and_rejects_external_changes() {
        let root = tempfile::tempdir().unwrap();
        let target = root.path().join("日报.xlsx");
        let frozen = root.path().join("frozen.xlsx");
        let report = root.path().join("report.xlsx");
        fs::write(&target, b"original").unwrap();
        fs::write(&frozen, b"original").unwrap();
        fs::write(&report, b"complete").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&target, fs::Permissions::from_mode(0o640)).unwrap();
        }
        let backup = write_back(&target, &frozen, &report).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"complete");
        assert_eq!(fs::read(&backup).unwrap(), b"original");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&target).unwrap().permissions().mode() & 0o777,
                0o640
            );
        }
        fs::write(&frozen, b"complete").unwrap();
        let second = write_back(&target, &frozen, &report).unwrap();
        assert_ne!(backup, second);
        assert_eq!(fs::read(&second).unwrap(), b"complete");
        fs::write(&target, b"external change").unwrap();
        assert!(
            write_back(&target, &frozen, &report)
                .unwrap_err()
                .to_string()
                .contains("已被修改")
        );
        assert_eq!(fs::read(target).unwrap(), b"external change");
    }

    #[test]
    fn readonly_template_is_not_overwritten() {
        let root = tempfile::tempdir().unwrap();
        let target = root.path().join("日报.xlsx");
        let frozen = root.path().join("frozen.xlsx");
        let report = root.path().join("report.xlsx");
        fs::write(&target, b"original").unwrap();
        fs::write(&frozen, b"original").unwrap();
        fs::write(&report, b"complete").unwrap();
        let original_permissions = fs::metadata(&target).unwrap().permissions();
        let mut readonly = original_permissions.clone();
        readonly.set_readonly(true);
        fs::set_permissions(&target, readonly).unwrap();
        let result = write_back(&target, &frozen, &report);
        fs::set_permissions(&target, original_permissions).unwrap();
        assert!(result.unwrap_err().to_string().contains("只读"));
        assert_eq!(fs::read(&target).unwrap(), b"original");
        assert!(!root.path().join("报表备份").exists());
    }

    #[cfg(windows)]
    #[test]
    fn locked_template_is_preserved_when_atomic_replace_fails() {
        use std::os::windows::fs::OpenOptionsExt;
        let root = tempfile::tempdir().unwrap();
        let target = root.path().join("日报.xlsx");
        let frozen = root.path().join("frozen.xlsx");
        let report = root.path().join("report.xlsx");
        fs::write(&target, b"original").unwrap();
        fs::write(&frozen, b"original").unwrap();
        fs::write(&report, b"complete").unwrap();
        let _locked = fs::OpenOptions::new()
            .read(true)
            .share_mode(1)
            .open(&target)
            .unwrap();
        assert!(write_back(&target, &frozen, &report).is_err());
        assert_eq!(fs::read(target).unwrap(), b"original");
    }
}
