use anyhow::{Context, Result, bail};
use financial_engine::{Request, report, workbook};
use std::{env, fs, path::Path};
fn main() -> Result<()> {
    let args: Vec<_> = env::args().collect();
    if args.len() < 3 {
        bail!("用法：financial-engine <simple|daily> request.json [template.xlsx output.xlsx]")
    }
    let req: Request = serde_json::from_str(&fs::read_to_string(&args[2])?)?;
    let result = match args[1].as_str() {
        "simple" => match args.get(3) {
            Some(template) => report::simple_for_template(&req, Path::new(template))?,
            None => report::simple(&req)?,
        },
        "daily" => report::daily(&req, Path::new(args.get(3).context("日报需要模板")?))?,
        _ => bail!("未知报表类型"),
    };
    if args.len() == 5 {
        workbook::write(Path::new(&args[3]), Path::new(&args[4]), &result.updates)?;
    }
    println!("{}", serde_json::to_string_pretty(&result)?);
    Ok(())
}
