mod fuel;
pub mod report;
pub mod source;
pub mod workbook;

use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum Cell {
    Number(String),
    Text(String),
    Formula(String),
    Blank,
}
pub type Cells = BTreeMap<String, Cell>;
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SheetUpdate {
    pub cells: Cells,
    #[serde(default)]
    pub formats: BTreeMap<String, u32>,
}
pub type Updates = BTreeMap<String, SheetUpdate>;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Request {
    pub sources: BTreeMap<String, PathBuf>,
    pub day: u32,
    #[serde(default = "three")]
    pub divisor: String,
    #[serde(default = "three")]
    pub count_divisor: String,
    #[serde(default)]
    pub closing_balance: String,
}
fn three() -> String {
    "3".into()
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Report {
    pub updates: Updates,
    pub notes: Vec<String>,
}
pub mod receipts;
