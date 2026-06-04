const jwt = require("jsonwebtoken");
const https = require("https");
const fs = require("fs");
const path = require("path");

const AK = "AmnHbnDffP4DamGLCfbhgbaEktR4nTyT";
const SK = "ABAaPCbAbyBhPNf4QMnLYpC4gLyA3AQC";
const BASE = "https://api-beijing.klingai.com";

function makeToken() {
  const now = Math.floor(Date.now() / 1000);
  return jwt.sign({ iss: AK, exp: now + 1800, nbf: now - 5 }, SK, {
    algorithm: "HS256",
    header: { alg: "HS256", typ: "JWT" },
  });
}

function apiRequest(method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(BASE + urlPath);
    const data = body ? JSON.stringify(body) : null;
    const opts = {
      hostname: url.hostname,
      path: url.pathname,
      method,
      headers: {
        Authorization: "Bearer " + makeToken(),
        "Content-Type": "application/json",
      },
    };
    if (data) opts.headers["Content-Length"] = Buffer.byteLength(data);

    const req = https.request(opts, (res) => {
      let chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString()));
        } catch (e) {
          reject(new Error("JSON parse error: " + Buffer.concat(chunks).toString().slice(0, 200)));
        }
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith("https") ? https : require("http");
    mod.get(url, (res) => {
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

async function generateAndPoll(prompt, outputPath) {
  console.log(`\n[提交] ${path.basename(outputPath)}`);
  console.log(`  prompt: ${prompt.slice(0, 80)}...`);

  const resp = await apiRequest("POST", "/v1/images/generations", {
    model: "kling-v1",
    prompt,
    n: 1,
    aspect_ratio: "3:4",
  });

  if (resp.code !== 0) {
    console.error(`  提交失败: ${resp.message || JSON.stringify(resp)}`);
    return null;
  }

  const taskId = resp.data.task_id;
  console.log(`  task_id: ${taskId}`);

  let delay = 4000;
  const maxWait = 180000;
  let elapsed = 0;

  while (elapsed < maxWait) {
    await sleep(delay);
    elapsed += delay;

    const st = await apiRequest("GET", `/v1/images/generations/${taskId}`);
    const status = st.data?.task_status;

    if (status === "succeed") {
      const imgUrl = st.data.task_result.images[0].url;
      console.log(`  成功! 下载中...`);
      await downloadFile(imgUrl, outputPath);
      console.log(`  已保存: ${outputPath}`);
      return outputPath;
    }
    if (status === "failed") {
      console.error(`  生成失败: ${st.data?.task_status_msg}`);
      return null;
    }
    console.log(`  轮询中... status=${status} elapsed=${elapsed / 1000}s`);
    delay = Math.min(delay * 1.3, 15000);
  }
  console.error(`  超时`);
  return null;
}

const CHARACTERS = [
  {
    key: "su_wan",
    front: "portrait photo of a young Chinese woman, long straight deep chestnut brown hair with layered bangs, almond-shaped warm brown eyes, heart-shaped face, white V-neck tee under camel knit cardigan, delicate gold necklace, elegant and warm expression, natural beauty, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
    side: "portrait photo of a young Chinese woman, long straight deep chestnut brown hair with layered bangs, almond-shaped warm brown eyes, heart-shaped face, white V-neck tee under camel knit cardigan, delicate gold necklace, elegant and warm expression, natural beauty, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  },
  {
    key: "lin_yue",
    front: "portrait photo of a young Chinese woman, medium-length wavy dark caramel hair with air bangs, thin gold round glasses, oval face with dimples, cream knit sweater, bookish and warm expression, soft smile, intellectual style, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
    side: "portrait photo of a young Chinese woman, medium-length wavy dark caramel hair with air bangs, thin gold round glasses, oval face with dimples, cream knit sweater, bookish and warm expression, soft smile, intellectual style, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  },
  {
    key: "chen_xing",
    front: "portrait photo of a young Chinese woman, shoulder-length copper brown hair with air bangs, bright expressive eyes, shallow dimples, denim jacket over striped tee, playful and energetic expression, youthful sporty casual style, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
    side: "portrait photo of a young Chinese woman, shoulder-length copper brown hair with air bangs, bright expressive eyes, shallow dimples, denim jacket over striped tee, playful and energetic expression, youthful sporty casual style, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  },
  {
    key: "ye_cheng",
    front: "portrait photo of a young Chinese woman, chin-length dark espresso bob haircut with subtle burgundy tips, defined oval face, cool-toned fair skin, black mock-neck sweater, minimalist silver stud earrings, cool and mysterious expression, indie aesthetic, soft studio lighting, upper body shot, facing camera, clean background, high quality realistic photo",
    side: "portrait photo of a young Chinese woman, chin-length dark espresso bob haircut with subtle burgundy tips, defined oval face, cool-toned fair skin, black mock-neck sweater, minimalist silver stud earrings, cool and mysterious expression, indie aesthetic, soft studio lighting, upper body shot, three-quarter view slightly turned right, clean background, high quality realistic photo",
  },
];

async function main() {
  const outDir = path.join(__dirname, "config", "character_refs");
  fs.mkdirSync(outDir, { recursive: true });

  console.log("=== 开始生成角色参考图 (8张) ===\n");

  for (const char of CHARACTERS) {
    const frontPath = path.join(outDir, `${char.key}_front.png`);
    const sidePath = path.join(outDir, `${char.key}_side.png`);

    if (!fs.existsSync(frontPath)) {
      await sleep(2000);
      await generateAndPoll(char.front, frontPath);
    } else {
      console.log(`\n[跳过] ${char.key}_front.png 已存在`);
    }

    if (!fs.existsSync(sidePath)) {
      await sleep(2000);
      await generateAndPoll(char.side, sidePath);
    } else {
      console.log(`\n[跳过] ${char.key}_side.png 已存在`);
    }
  }

  console.log("\n=== 全部完成 ===");
  const files = fs.readdirSync(outDir).filter(f => f.endsWith(".png"));
  console.log(`生成了 ${files.length}/8 张参考图:`);
  files.forEach(f => console.log(`  ${f}`));
}

main().catch(e => { console.error("Fatal:", e); process.exit(1); });
