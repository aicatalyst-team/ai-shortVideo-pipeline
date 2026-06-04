const jwt = require("jsonwebtoken");
const https = require("https");
const fs = require("fs");
const path = require("path");

const AK = "AmnHbnDffP4DamGLCfbhgbaEktR4nTyT";
const SK = "ABAaPCbAbyBhPNf4QMnLYpC4gLyA3AQC";
const BASE_HOST = "api-beijing.klingai.com";

function makeToken() {
  const now = Math.floor(Date.now() / 1000);
  return jwt.sign({ iss: AK, exp: now + 1800, nbf: now - 5 }, SK, {
    algorithm: "HS256",
    header: { alg: "HS256", typ: "JWT" },
  });
}

function apiPost(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = https.request({
      hostname: BASE_HOST,
      path: urlPath,
      method: "POST",
      headers: {
        Authorization: "Bearer " + makeToken(),
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data),
        Connection: "close",
      },
      agent: false,
    }, (res) => {
      let chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString())); }
        catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function apiGet(urlPath) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: BASE_HOST,
      path: urlPath,
      method: "GET",
      headers: {
        Authorization: "Bearer " + makeToken(),
        Connection: "close",
      },
      agent: false,
    }, (res) => {
      let chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString())); }
        catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.end();
  });
}

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    https.get(url, { agent: false, headers: { Connection: "close" } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return downloadFile(res.headers.location, dest).then(resolve).catch(reject);
      }
      const ws = fs.createWriteStream(dest);
      res.pipe(ws);
      ws.on("finish", () => { ws.close(); resolve(dest); });
    }).on("error", reject);
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// 命令行参数: node gen_one.js <key> <front|side>
const charKey = process.argv[2];
const view = process.argv[3]; // "front" or "side"

if (!charKey || !view) {
  console.log("用法: node gen_one.js <su_wan|lin_yue|chen_xing|ye_cheng> <front|side>");
  process.exit(1);
}

const PROMPTS = {
  su_wan_front: "portrait photo of a young Chinese woman, long straight deep chestnut brown hair with layered bangs, almond-shaped warm brown eyes, heart-shaped face, white V-neck tee under camel knit cardigan, delicate gold necklace, elegant and warm expression, natural beauty, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
  su_wan_side: "portrait photo of a young Chinese woman, long straight deep chestnut brown hair with layered bangs, almond-shaped warm brown eyes, heart-shaped face, white V-neck tee under camel knit cardigan, delicate gold necklace, elegant and warm expression, natural beauty, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  lin_yue_front: "portrait photo of a young Chinese woman, medium-length wavy dark caramel hair with air bangs, thin gold round glasses, oval face with dimples, cream knit sweater, bookish and warm expression, soft smile, intellectual style, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
  lin_yue_side: "portrait photo of a young Chinese woman, medium-length wavy dark caramel hair with air bangs, thin gold round glasses, oval face with dimples, cream knit sweater, bookish and warm expression, soft smile, intellectual style, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  chen_xing_front: "portrait photo of a young Chinese woman, shoulder-length copper brown hair with air bangs, bright expressive eyes, shallow dimples, denim jacket over striped tee, playful and energetic expression, youthful sporty casual style, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
  chen_xing_side: "portrait photo of a young Chinese woman, shoulder-length copper brown hair with air bangs, bright expressive eyes, shallow dimples, denim jacket over striped tee, playful and energetic expression, youthful sporty casual style, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  ye_cheng_front: "portrait photo of a young Chinese woman, chin-length dark espresso bob haircut with subtle burgundy tips, defined oval face, cool-toned fair skin, black mock-neck sweater, minimalist silver stud earrings, cool and mysterious expression, indie aesthetic, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
  ye_cheng_side: "portrait photo of a young Chinese woman, chin-length dark espresso bob haircut with subtle burgundy tips, defined oval face, cool-toned fair skin, black mock-neck sweater, minimalist silver stud earrings, cool and mysterious expression, indie aesthetic, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
};

async function main() {
  const promptKey = `${charKey}_${view}`;
  const prompt = PROMPTS[promptKey];
  if (!prompt) {
    console.error(`未知: ${promptKey}`);
    process.exit(1);
  }

  const outDir = path.join(__dirname, "config", "character_refs");
  fs.mkdirSync(outDir, { recursive: true });
  const outputPath = path.join(outDir, `${promptKey}.png`);

  console.log(`[提交] ${promptKey}`);
  const resp = await apiPost("/v1/images/generations", {
    model: "kling-v1",
    prompt,
    n: 1,
    aspect_ratio: "3:4",
  });

  if (resp.code !== 0) {
    console.error(`提交失败: code=${resp.code} msg=${resp.message}`);
    console.error(JSON.stringify(resp));
    process.exit(1);
  }

  const taskId = resp.data.task_id;
  console.log(`task_id: ${taskId}`);

  let delay = 4000;
  let elapsed = 0;
  const maxWait = 180000;

  while (elapsed < maxWait) {
    await sleep(delay);
    elapsed += delay;

    const st = await apiGet(`/v1/images/generations/${taskId}`);
    const status = st.data?.task_status;

    if (status === "succeed") {
      const imgUrl = st.data.task_result.images[0].url;
      console.log("成功! 下载...");
      await downloadFile(imgUrl, outputPath);
      console.log(`已保存: ${outputPath}`);
      process.exit(0);
    }
    if (status === "failed") {
      console.error(`失败: ${st.data?.task_status_msg}`);
      process.exit(1);
    }
    console.log(`轮询... status=${status} ${elapsed/1000}s`);
    delay = Math.min(delay * 1.3, 15000);
  }
  console.error("超时");
  process.exit(1);
}

main().catch(e => { console.error(e); process.exit(1); });
