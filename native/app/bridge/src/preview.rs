use anyhow::{Context, Result, ensure};
use calamine::Reader;
use nsh_core::ui::prelude::*;
use std::path::Path;
#[derive(Clone, JsObject)]
pub struct TablePage {
    pub sheets: Vec<String>,
    pub sheet: String,
    pub rows: Vec<Vec<String>>,
    pub total: u32,
    pub start: u32,
}
pub fn table(path: &Path, sheet: &str, offset: u32) -> Result<TablePage> {
    if path
        .extension()
        .is_some_and(|v| v.eq_ignore_ascii_case("csv"))
    {
        let rows = csv::ReaderBuilder::new()
            .has_headers(false)
            .flexible(true)
            .from_path(path)?
            .records()
            .map(|r| r.map(|r| r.iter().map(str::to_owned).collect::<Vec<_>>()))
            .collect::<std::result::Result<Vec<_>, _>>()?;
        return Ok(TablePage {
            total: rows.len() as u32,
            rows: rows.into_iter().skip(offset as usize).take(100).collect(),
            sheets: vec!["CSV".into()],
            sheet: "CSV".into(),
            start: offset,
        });
    }
    let mut book = calamine::open_workbook_auto(path)?;
    let sheets = book.sheet_names().to_vec();
    let sheet = if sheet.is_empty() {
        sheets.first().context("工作簿没有工作表")?.clone()
    } else {
        sheet.into()
    };
    let range = book.worksheet_range(&sheet)?;
    let total = range.end().map_or(0, |(r, _)| r + 1);
    let start = range.start().unwrap_or_default();
    let rows = (offset..total.min(offset + 100))
        .map(|r| {
            (0..range.end().map_or(0, |(_, c)| c + 1))
                .map(|c| {
                    if r < start.0 || c < start.1 {
                        String::new()
                    } else {
                        range
                            .get_value((r, c))
                            .map(ToString::to_string)
                            .unwrap_or_default()
                    }
                })
                .collect()
        })
        .collect();
    Ok(TablePage {
        sheets,
        sheet,
        rows,
        total,
        start: offset,
    })
}
pub fn image_data(path: &Path) -> Result<String> {
    use base64::Engine;
    let bytes = image_bytes(path)?;
    Ok(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(bytes)
    ))
}
pub fn image_bytes(path: &Path) -> Result<Vec<u8>> {
    ensure!(
        std::fs::metadata(path)?.len() <= 20 * 1024 * 1024,
        "图片超过 20 MB"
    );
    let mut reader = image::ImageReader::open(path)?.with_guessed_format()?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(16384);
    limits.max_image_height = Some(16384);
    limits.max_alloc = Some(256 * 1024 * 1024);
    reader.limits(limits);
    let image = reader.decode().context("无法读取图片")?;
    let mut result = std::io::Cursor::new(Vec::new());
    image.write_to(&mut result, image::ImageFormat::Png)?;
    Ok(result.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn csv_preview_pagination_keeps_every_row() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("source.csv");
        std::fs::write(
            &path,
            (0..205).map(|n| format!("{n},行{n}\n")).collect::<String>(),
        )
        .unwrap();
        let p = table(&path, "", 100).unwrap();
        assert_eq!(p.total, 205);
        assert_eq!(p.start, 100);
        assert_eq!(p.rows.len(), 100);
        assert_eq!(p.rows[0][1], "行100");
        assert_eq!(table(&path, "", 200).unwrap().rows.len(), 5);
    }
    #[test]
    fn legacy_bmp_and_tiff_are_normalized_for_preview_and_recognition() {
        let dir = tempfile::tempdir().unwrap();
        for ext in ["bmp", "tiff"] {
            let path = dir.path().join(format!("receipt.{ext}"));
            image::RgbImage::from_pixel(4, 3, image::Rgb([20, 60, 30]))
                .save(&path)
                .unwrap();
            let bytes = image_bytes(&path).unwrap();
            assert!(bytes.starts_with(b"\x89PNG"));
            assert_eq!(image::load_from_memory(&bytes).unwrap().width(), 4);
        }
    }
}
