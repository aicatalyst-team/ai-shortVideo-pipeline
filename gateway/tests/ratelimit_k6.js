// k6 ratelimit load test
//
// Usage:
//   k6 run -e GATEWAY=http://localhost:8080 -e TOKEN=<JWT> tests/ratelimit_k6.js
//
// Expected:
//   - regenerate route triggers many 429 responses under burst load.
//   - 429 responses include Retry-After plus JSON body {error, retry_after_sec, trace_id}.

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const counter200 = new Counter('http_200');
const counter429 = new Counter('http_429');
const rate429 = new Rate('rate_429');

export const options = {
  scenarios: {
    user_burst: {
      executor: 'constant-arrival-rate',
      rate: 30,
      timeUnit: '1s',
      duration: '20s',
      preAllocatedVUs: 10,
      exec: 'hitRegenerate',
    },
    global_burst: {
      executor: 'constant-arrival-rate',
      rate: 100,
      timeUnit: '1s',
      duration: '20s',
      preAllocatedVUs: 50,
      startTime: '25s',
      exec: 'hitRegenerateMultiUser',
    },
  },
  thresholds: {
    rate_429: ['rate>0.5'],
    http_req_duration: ['p(95)<1000'],
  },
};

const GATEWAY = __ENV.GATEWAY || 'http://localhost:8080';
const TOKEN = __ENV.TOKEN || '';
const CLIP_ID = __ENV.CLIP_ID || 'CLIPTEST';

export function hitRegenerate() {
  const url = `${GATEWAY}/api/v1/clips/${CLIP_ID}/regenerate`;
  const payload = JSON.stringify({ new_prompt: 'k6 ratelimit test' });
  const params = {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${TOKEN}`,
      'X-Trace-Id': `k6-${__VU}-${__ITER}`,
    },
  };

  const res = http.post(url, payload, params);
  recordResult(res);
}

export function hitRegenerateMultiUser() {
  hitRegenerate();
}

function recordResult(res) {
  if ([200, 202, 404, 409].includes(res.status)) {
    counter200.add(1);
    rate429.add(0);
    return;
  }

  if (res.status === 429) {
    counter429.add(1);
    rate429.add(1);
    check(res, {
      '429 has Retry-After header': (r) => r.headers['Retry-After'] !== undefined,
      '429 body has retry_after_sec': (r) => {
        try {
          return JSON.parse(r.body).retry_after_sec !== undefined;
        } catch (e) {
          return false;
        }
      },
      '429 body has trace_id': (r) => {
        try {
          return JSON.parse(r.body).trace_id !== undefined;
        } catch (e) {
          return false;
        }
      },
    });
    return;
  }

  console.warn(`unexpected status ${res.status}: ${res.body.substring(0, 200)}`);
}
