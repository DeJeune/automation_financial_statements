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
    let mut prompt = format!(
        "请读取加油站{category}截图，提取{}。只返回原始数值，不进行除以3或其他计算；无法识别的字段返回 null。抖音读取表格最后合计行；超市读取班次交款（含备用金）的现金。",
        fields.join("、")
    );
    if matches!(category, "国通1" | "国通2") {
        prompt.push_str("国通有两种表：订单汇总表提取订单金额和退款订单金额，交易明细金额合计返回 null；交易流水表（或金额列底部有合计的 Excel 表格）只读取金额列末行合计到交易明细金额合计，订单金额和退款订单金额均返回 null。不要把明细金额合计填入订单金额。不能自行加总、推算退款或把缺失字段当作 0；无法确认合计时返回 null。");
    }
    let body = json!({"contents":[{"role":"user","parts":[{"text":prompt},{"inlineData":{"mimeType":mime,"data":STANDARD.encode(bytes)}}]}],"generationConfig":{"temperature":0,"maxOutputTokens":5000,"responseMimeType":"application/json","responseSchema":{"type":"OBJECT","properties":properties,"required":fields}}});
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(90))
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    let response = request_with_retry(&client, &url, key, &body, category, std::thread::sleep)?;
    let reply: serde_json::Value = response.json().context("识别服务返回的响应不是 JSON")?;
    let text = reply["candidates"][0]["content"]["parts"]
        .as_array()
        .context("识别服务没有返回内容")?
        .iter()
        .filter_map(|p| p["text"].as_str())
        .collect::<String>();
    let result: serde_json::Value = serde_json::from_str(&text).context("图片识别结果格式无效")?;
    financial_engine::receipts::parse_fields(category, &result)?;
    Ok(result)
}

fn request_with_retry(
    client: &reqwest::blocking::Client,
    url: &url::Url,
    key: &str,
    body: &serde_json::Value,
    category: &str,
    mut pause: impl FnMut(Duration),
) -> Result<reqwest::blocking::Response> {
    const ATTEMPTS: u64 = 3;
    for attempt in 1..=ATTEMPTS {
        let error = match client
            .post(url.clone())
            .header("x-goog-api-key", key)
            .json(body)
            .send()
        {
            Ok(response) => {
                let status = response.status();
                if status.is_success() {
                    return Ok(response);
                }
                let error = anyhow::anyhow!(
                    "图片识别服务返回 HTTP {}，请检查配置或额度",
                    status.as_u16()
                );
                if status.as_u16() != 429 && !status.is_server_error() {
                    return Err(error);
                }
                error
            }
            Err(error) => {
                let retryable = !error.is_builder() && !error.is_redirect();
                let error = anyhow::Error::new(error.without_url())
                    .context("图片识别请求失败，请检查网络和 API 地址");
                if !retryable {
                    return Err(error);
                }
                error
            }
        };
        if attempt == ATTEMPTS {
            return Err(error.context(format!("图片识别重试失败，已尝试 {attempt} 次")));
        }
        let delay = Duration::from_secs(5 * attempt);
        crate::runtime::log(
            "WARN",
            &format!(
                "{category} 识别第 {attempt}/{ATTEMPTS} 次失败，{} 秒后重试：{error:#}",
                delay.as_secs()
            ),
        );
        pause(delay);
    }
    bail!("图片识别重试失败")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};

    fn read_request(stream: &mut TcpStream) -> String {
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut bytes = vec![];
        let mut chunk = [0u8; 4096];
        loop {
            let n = stream.read(&mut chunk).unwrap();
            assert!(n > 0, "request closed before its body was sent");
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(end) = bytes.windows(4).position(|b| b == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&bytes[..end]);
                let len = headers
                    .lines()
                    .find_map(|line| {
                        line.to_lowercase()
                            .strip_prefix("content-length: ")
                            .and_then(|value| value.parse::<usize>().ok())
                    })
                    .unwrap();
                if bytes.len() >= end + 4 + len {
                    return String::from_utf8(bytes).unwrap();
                }
            }
        }
    }

    fn provider(replies: Vec<Option<u16>>) -> (url::Url, std::thread::JoinHandle<usize>) {
        let server = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = server.local_addr().unwrap();
        server.set_nonblocking(true).unwrap();
        let thread = std::thread::spawn(move || {
            let mut requests = 0;
            for status in replies {
                let deadline = std::time::Instant::now() + Duration::from_secs(3);
                let mut stream = loop {
                    match server.accept() {
                        Ok((stream, _)) => break stream,
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            assert!(
                                std::time::Instant::now() < deadline,
                                "expected another request"
                            );
                            std::thread::sleep(Duration::from_millis(2));
                        }
                        Err(error) => panic!("{error}"),
                    }
                };
                stream.set_nonblocking(false).unwrap();
                assert!(read_request(&mut stream).contains("retry-test"));
                requests += 1;
                if let Some(status) = status {
                    write!(stream, "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}").unwrap();
                }
            }
            requests
        });
        (
            url::Url::parse(&format!("http://{address}")).unwrap(),
            thread,
        )
    }

    fn test_client() -> reqwest::blocking::Client {
        reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(3))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .unwrap()
    }

    #[test]
    fn network_and_server_errors_are_retried_before_success() {
        let (url, server) = provider(vec![None, Some(503), Some(200)]);
        let mut delays = vec![];
        let response = request_with_retry(
            &test_client(),
            &url,
            "api-secret",
            &json!({"retry-test": true}),
            "抖音",
            |delay| delays.push(delay.as_secs()),
        )
        .unwrap();
        assert_eq!(response.status().as_u16(), 200);
        assert_eq!(delays, [5, 10]);
        assert_eq!(server.join().unwrap(), 3);
    }

    #[test]
    fn rate_limits_are_retried() {
        let (url, server) = provider(vec![Some(429), Some(200)]);
        let mut delays = vec![];
        request_with_retry(
            &test_client(),
            &url,
            "api-secret",
            &json!({"retry-test": true}),
            "抖音",
            |delay| delays.push(delay.as_secs()),
        )
        .unwrap();
        assert_eq!(delays, [5]);
        assert_eq!(server.join().unwrap(), 2);
    }

    #[test]
    fn redirects_and_permanent_http_errors_are_not_retried() {
        for status in [302, 400, 401, 403, 404] {
            let (url, server) = provider(vec![Some(status)]);
            let error = request_with_retry(
                &test_client(),
                &url,
                "api-secret",
                &json!({"retry-test": true}),
                "抖音",
                |_| panic!("permanent error must not be retried"),
            )
            .unwrap_err();
            assert!(error.to_string().contains(&format!("HTTP {status}")));
            assert_eq!(server.join().unwrap(), 1);
        }
    }

    #[test]
    fn transient_failures_stop_after_three_attempts_and_hide_credentials() {
        for status in [None, Some(503)] {
            let (mut url, server) = provider(vec![status; 3]);
            url.set_query(Some("token=url-secret"));
            let mut delays = vec![];
            let error = request_with_retry(
                &test_client(),
                &url,
                "api-secret",
                &json!({"retry-test": true}),
                "抖音",
                |delay| delays.push(delay.as_secs()),
            )
            .unwrap_err();
            let message = format!("{error:#}");
            assert!(message.contains("3 次"));
            assert!(!message.contains("url-secret"));
            assert!(!message.contains("api-secret"));
            assert!(error.chain().count() > 1);
            assert_eq!(delays, [5, 10]);
            assert_eq!(server.join().unwrap(), 3);
        }
    }
    fn recognized_fields(data: serde_json::Value) -> serde_json::Value {
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
            assert!(raw.contains("交易流水表"));
            assert!(raw.contains("交易明细金额合计"));
            let body = json!({"candidates":[{"content":{"parts":[{"text":data.to_string()}]}}]})
                .to_string();
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
        thread.join().unwrap();
        result
    }

    #[test]
    fn provider_boundary_extracts_raw_fields() {
        for data in [
            json!({"订单金额":"300元","退款订单金额":"30元"}),
            json!({"订单金额":null,"退款订单金额":null,"交易明细金额合计":"13307.06"}),
        ] {
            assert_eq!(recognized_fields(data.clone()), data);
        }
    }
}
