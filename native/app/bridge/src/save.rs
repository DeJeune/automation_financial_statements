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
    complete
        .as_file()
        .set_permissions(writable_permissions(permissions.clone()))?;
    complete.as_file_mut().sync_all()?;
    ensure!(
        fs::read(template)? == original,
        "保存前模板已被修改，请重新计算，未覆盖文件"
    );
    replace_template(template, complete, permissions)?;
    Ok(backup_path)
}

fn writable_permissions(mut permissions: fs::Permissions) -> fs::Permissions {
    if permissions.readonly() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            permissions.set_mode(permissions.mode() | 0o200);
        }
        #[cfg(not(unix))]
        {
            // Clears the Windows attribute; Unix only gains owner-write above.
            #[allow(clippy::permissions_set_readonly_false)]
            permissions.set_readonly(false);
        }
    }
    permissions
}

fn replace_template(
    template: &Path,
    complete: tempfile::NamedTempFile,
    original_permissions: fs::Permissions,
) -> Result<()> {
    let readonly = original_permissions.readonly();
    if readonly {
        fs::set_permissions(template, writable_permissions(original_permissions.clone()))
            .context("无法解除模板的只读属性，请检查该文件的修改权限；未覆盖文件")?;
    }
    if let Err(error) = complete.persist(template) {
        if readonly {
            fs::set_permissions(template, original_permissions).with_context(|| {
                format!(
                    "保存失败且无法恢复模板的只读属性：{}；请检查文件权限",
                    error.error
                )
            })?;
        }
        return Err(error.error).with_context(|| {
            format!(
                "无法保存 {}，请关闭 Excel/WPS 并检查目录权限后重新计算；原文件保持不变",
                template.display()
            )
        });
    }
    Ok(())
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
    fn readonly_template_becomes_writable_and_keeps_a_backup() {
        let root = tempfile::tempdir().unwrap();
        let target = root.path().join("日报.xlsx");
        let frozen = root.path().join("frozen.xlsx");
        let report = root.path().join("report.xlsx");
        fs::write(&target, b"original").unwrap();
        fs::write(&frozen, b"original").unwrap();
        fs::write(&report, b"complete").unwrap();
        let mut readonly = fs::metadata(&target).unwrap().permissions();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            readonly.set_mode(0o440);
        }
        readonly.set_readonly(true);
        fs::set_permissions(&target, readonly).unwrap();
        let backup = write_back(&target, &frozen, &report).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"complete");
        assert_eq!(fs::read(backup).unwrap(), b"original");
        let saved_permissions = fs::metadata(&target).unwrap().permissions();
        assert!(!saved_permissions.readonly());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(saved_permissions.mode() & 0o777, 0o640);
        }
    }

    #[test]
    fn failed_report_does_not_change_readonly_template_permissions() {
        let root = tempfile::tempdir().unwrap();
        let target = root.path().join("日报.xlsx");
        let frozen = root.path().join("frozen.xlsx");
        fs::write(&target, b"original").unwrap();
        fs::write(&frozen, b"original").unwrap();
        let permissions = fs::metadata(&target).unwrap().permissions();
        let mut readonly = permissions.clone();
        readonly.set_readonly(true);
        fs::set_permissions(&target, readonly).unwrap();
        assert!(write_back(&target, &frozen, &root.path().join("missing.xlsx")).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"original");
        assert!(fs::metadata(&target).unwrap().permissions().readonly());
        fs::set_permissions(&target, permissions).unwrap();
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

    #[cfg(windows)]
    #[test]
    fn readonly_attribute_is_restored_if_replacement_fails() {
        use std::os::windows::fs::OpenOptionsExt;
        let root = tempfile::tempdir().unwrap();
        let target = root.path().join("简表.xlsx");
        let frozen = root.path().join("frozen.xlsx");
        let report = root.path().join("report.xlsx");
        fs::write(&target, b"original").unwrap();
        fs::write(&frozen, b"original").unwrap();
        fs::write(&report, b"complete").unwrap();
        let permissions = fs::metadata(&target).unwrap().permissions();
        let mut readonly = permissions.clone();
        readonly.set_readonly(true);
        fs::set_permissions(&target, readonly).unwrap();
        let locked = fs::OpenOptions::new()
            .read(true)
            .share_mode(1 | 2)
            .open(&target)
            .unwrap();
        assert!(write_back(&target, &frozen, &report).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"original");
        assert!(fs::metadata(&target).unwrap().permissions().readonly());
        drop(locked);
        fs::set_permissions(&target, permissions).unwrap();
    }
}
