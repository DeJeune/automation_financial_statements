use anyhow::{Context, Result, bail, ensure};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::json;
use std::{collections::BTreeMap, path::Path, time::Duration};

pub fn recognize(
    category: &str,
    path: &Path,
    base: &str,
    key: &str,
    model: &str,
) -> Result<serde_json::Value> {
    ensure!(
        !key.trim().is_empty(),
        "识别图片前，请在设置中填写 Gemini API Key"
    );
    let mut url = url::Url::parse(base).context("API 地址无效")?;
    ensure!(
        url.scheme() == "https"
            || (url.scheme() == "http"
                && matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "::1"))),
        "API 地址需使用 HTTPS"
    );
    ensure!(
        url.username().is_empty() && url.password().is_none(),
        "API 地址不能包含登录信息"
    );
    ensure!(
        !model.is_empty()
            && model
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.')),
        "模型名称无效"
    );
    let root = url.path().trim_end_matches('/');
    let version = if root.ends_with("/v1beta") || root.ends_with("/v1") {
        root.to_string()
    } else {
        format!("{root}/v1beta")
    };
    url.set_path(&format!("{version}/models/{model}:generateContent"));
    url.set_query(None);
    url.set_fragment(None);
    ensure!(
        std::fs::metadata(path)?.len() <= 20 * 1024 * 1024,
        "图片超过 20 MB，请缩小后再上传"
    );
    let bytes = std::fs::read(path)?;
    let mut bytes = bytes;
    let mime = if bytes.starts_with(b"\x89PNG") {
        "image/png"
    } else if bytes.starts_with(b"\xff\xd8\xff") {
        "image/jpeg"
    } else if bytes.len() > 12 && &bytes[8..12] == b"WEBP" {
        "image/webp"
    } else {
        bytes = crate::preview::image_bytes(path)?;
        "image/png"
    };
    let fields = financial_engine::receipts::fields(category)?;
    let properties: BTreeMap<_, _> = fields
        .iter()
        .map(|f| (*f, json!({"type":"STRING","nullable":true})))
        .collect();
    let prompt = format!(
        "请读取加油站{category}截图，提取{}。只返回原始数值，不进行除以3或其他计算；无法识别的字段返回 null。抖音读取表格最后合计行；超市读取班次交款（含备用金）的现金。",
        fields.join("、")
    );
    let body = json!({"contents":[{"role":"user","parts":[{"text":prompt},{"inlineData":{"mimeType":mime,"data":STANDARD.encode(bytes)}}]}],"generationConfig":{"temperature":0,"maxOutputTokens":5000,"responseMimeType":"application/json","responseSchema":{"type":"OBJECT","properties":properties,"required":fields}}});
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(90))
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    for attempt in 0..3 {
        let response = client
            .post(url.clone())
            .header("x-goog-api-key", key)
            .json(&body)
            .send()
            .map_err(|_| anyhow::anyhow!("图片识别请求失败，请检查网络和 API 地址"))?;
        let status = response.status();
        if (status.as_u16() == 429 || status.is_server_error()) && attempt < 2 {
            std::thread::sleep(Duration::from_secs(5 * (attempt + 1)));
            continue;
        }
        ensure!(
            status.is_success(),
            "图片识别服务返回 HTTP {}，请检查配置或额度",
            status.as_u16()
        );
        let reply: serde_json::Value = response.json().context("识别服务返回的响应不是 JSON")?;
        let text = reply["candidates"][0]["content"]["parts"]
            .as_array()
            .context("识别服务没有返回内容")?
            .iter()
            .filter_map(|p| p["text"].as_str())
            .collect::<String>();
        let result: serde_json::Value =
            serde_json::from_str(&text).context("图片识别结果格式无效")?;
        for field in &fields {
            financial_engine::receipts::parse(&result[*field])
                .with_context(|| format!("{category} / {field}"))?;
        }
        return Ok(result);
    }
    bail!("图片识别重试失败")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    #[test]
    fn provider_boundary_extracts_raw_fields() {
        let server = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = server.local_addr().unwrap();
        let thread = std::thread::spawn(move || {
            let (mut stream, _) = server.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut bytes = vec![];
            let mut chunk = [0u8; 4096];
            loop {
                let n = stream.read(&mut chunk).unwrap();
                if n == 0 {
                    break;
                }
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(end) = bytes.windows(4).position(|b| b == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..end]);
                    let len = headers
                        .lines()
                        .find_map(|l| {
                            l.to_lowercase()
                                .strip_prefix("content-length: ")
                                .and_then(|v| v.parse::<usize>().ok())
                        })
                        .unwrap();
                    if bytes.len() >= end + 4 + len {
                        break;
                    }
                }
            }
            let raw = String::from_utf8_lossy(&bytes);
            assert!(raw.starts_with("POST /v1beta/models/test-model:generateContent "));
            assert!(raw.contains("x-goog-api-key: test-key"));
            assert!(raw.contains("inlineData"));
            let body=json!({"candidates":[{"content":{"parts":[{"text":"{\"订单金额\":\"300元\",\"退款订单金额\":\"30元\"}"}]}}]}).to_string();
            write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
        });
        let image = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(image.path(), b"\x89PNGfixture").unwrap();
        let result = recognize(
            "国通1",
            image.path(),
            &format!("http://{address}"),
            "test-key",
            "test-model",
        )
        .unwrap();
        assert_eq!(result["订单金额"], "300元");
        thread.join().unwrap();
    }
}
