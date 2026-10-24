//! Saved station profiles contain no daily inputs, credentials or results.
use anyhow::{Context, Result};
use nsh_core::ui::prelude::*;
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, io::Write, path::Path};

#[derive(Clone, Serialize, Deserialize, JsObject)]
pub struct Station {
    pub id: String,
    pub number: u32,
    pub name: String,
    pub gas_price: String,
}

#[derive(Clone, Default, Serialize, Deserialize, JsObject)]
pub struct Stations {
    pub stations: Vec<Station>,
    pub selected_id: String,
}

fn validate(value: &Stations) -> Result<()> {
    let mut ids = BTreeSet::new();
    let mut numbers = BTreeSet::new();
    for station in &value.stations {
        anyhow::ensure!(
            !station.id.is_empty()
                && station.number > 0
                && ids.insert(&station.id)
                && numbers.insert(station.number),
            "加油站列表包含无效或重复的编号"
        );
    }
    anyhow::ensure!(
        value.selected_id.is_empty() || ids.contains(&value.selected_id),
        "所选加油站不在列表中"
    );
    Ok(())
}

pub fn load(root: &Path) -> Result<Stations> {
    let path = root.join("stations.json");
    match std::fs::read(path) {
        Ok(bytes) => {
            let value = serde_json::from_slice(&bytes).context("加油站列表损坏，原文件已保留")?;
            validate(&value)?;
            Ok(value)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Stations::default()),
        Err(e) => Err(e).context("无法读取加油站列表"),
    }
}

pub fn save(root: &Path, value: &Stations) -> Result<()> {
    validate(value)?;
    let mut tmp = tempfile::NamedTempFile::new_in(root)?;
    tmp.write_all(&serde_json::to_vec_pretty(value)?)?;
    tmp.as_file().sync_all()?;
    tmp.persist(root.join("stations.json"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profiles_survive_reload_and_removal_without_daily_data() {
        let dir = tempfile::tempdir().unwrap();
        assert!(load(dir.path()).unwrap().stations.is_empty());
        let mut value = Stations {
            stations: vec![
                Station {
                    id: "a".into(),
                    number: 1,
                    name: "城东站".into(),
                    gas_price: "8.21".into(),
                },
                Station {
                    id: "b".into(),
                    number: 2,
                    name: "城西站".into(),
                    gas_price: "9.12".into(),
                },
            ],
            selected_id: "b".into(),
        };
        save(dir.path(), &value).unwrap();
        let restored = load(dir.path()).unwrap();
        assert_eq!(restored.selected_id, "b");
        assert_eq!(restored.stations[0].name, "城东站");
        assert_eq!(restored.stations[1].gas_price, "9.12");
        let json: serde_json::Value =
            serde_json::from_slice(&std::fs::read(dir.path().join("stations.json")).unwrap())
                .unwrap();
        assert_eq!(json["stations"][0].as_object().unwrap().len(), 4);
        value.stations.remove(0);
        save(dir.path(), &value).unwrap();
        assert_eq!(load(dir.path()).unwrap().stations.len(), 1);
        value.stations.push(value.stations[0].clone());
        assert!(save(dir.path(), &value).is_err());
        assert_eq!(load(dir.path()).unwrap().stations.len(), 1);
    }

    #[test]
    fn unreadable_profiles_are_not_treated_as_an_empty_list() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("stations.json");
        std::fs::write(&path, "broken").unwrap();
        assert!(load(dir.path()).is_err());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "broken");
        std::fs::remove_file(&path).unwrap();
        std::fs::create_dir(&path).unwrap();
        assert!(load(dir.path()).is_err());
    }
}
