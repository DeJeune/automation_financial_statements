//! Disposable template selections for UI tests. Excluded from release builds.
use nsh_core::ui::prelude::*;
use std::sync::{Mutex, OnceLock};

static DIRECTORIES: OnceLock<Mutex<Vec<tempfile::TempDir>>> = OnceLock::new();

#[module]
/// Disposable workbook selections available only in development builds.
pub struct TestFiles;
#[module]
impl TestFiles {
    /// Copy a committed synthetic workbook so UI tests can exercise real write-back.
    pub fn template(name: String) -> Result<String, String> {
        let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../fixtures")
            .join(&name);
        if !matches!(
            name.as_str(),
            "simple.xlsx" | "daily.xlsx" | "invalid-daily.xlsx"
        ) {
            return Err("Unknown synthetic template".into());
        }
        let directory = tempfile::tempdir().map_err(|e| e.to_string())?;
        let target = directory.path().join(name);
        std::fs::copy(source, &target).map_err(|e| e.to_string())?;
        let path = target.to_string_lossy().into_owned();
        DIRECTORIES
            .get_or_init(Default::default)
            .lock()
            .map_err(|_| "Test directory unavailable")?
            .push(directory);
        Ok(path)
    }
}
