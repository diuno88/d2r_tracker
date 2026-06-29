/**
 * D2R Tracker OCR Worker
 * Python 프로세스에서 subprocess로 실행
 * stdin으로 JSON 명령 수신, stdout으로 JSON 결과 반환
 *
 * 통신 프로토콜:
 *   Python → Node:  {"action": "ocr", "imagePath": "...", "lang": "kor+eng"}\n
 *   Node → Python:  {"success": true, "lines": [...], "rawText": "..."}\n
 *   Python → Node:  {"action": "exit"}\n
 */

const { createWorker } = require('tesseract.js');
const path = require('path');
const readline = require('readline');

// tesseract 학습 데이터 경로
// 환경변수 TESSDATA_PATH 우선, 없으면 개발 환경 기본값
const TESSDATA_PATH = process.env.TESSDATA_PATH
  || path.join(__dirname, '..', '..', 'extension', 'data');

let ocrWorker = null;
let isReady = false;

async function initOCR() {
  try {
    ocrWorker = await createWorker(['kor', 'eng'], 1, {
      langPath: TESSDATA_PATH,
      gzip: true,
      logger: () => {},
      errorHandler: () => {}
    });
    isReady = true;
    sendResult({ type: 'ready', message: 'OCR Worker initialized' });
  } catch (err) {
    sendResult({ type: 'error', message: `OCR 초기화 실패: ${err.message}` });
    process.exit(1);
  }
}

function sendResult(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

async function runOCR(imagePath, lang) {
  if (!isReady || !ocrWorker) {
    return { success: false, error: 'OCR worker not ready' };
  }

  try {
    // 언어 설정 변경이 필요한 경우
    if (lang && lang !== 'kor+eng') {
      // 요청된 언어가 다를 때는 현재 worker 재사용 (kor+eng로 초기화됨)
    }

    const result = await ocrWorker.recognize(imagePath);
    const rawText = result.data.text || '';

    // 텍스트를 줄 단위로 분리, 빈 줄 제거
    const lines = rawText
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.length > 0);

    // bbox 정보 포함한 라인 (단어 단위)
    const words = result.data.words || [];
    const linesWithBbox = buildLinesWithBbox(words);

    return {
      success: true,
      lines,
      rawText,
      linesWithBbox,
      confidence: result.data.confidence
    };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

/**
 * 단어 목록에서 라인별 bbox 정보 구성
 */
function buildLinesWithBbox(words) {
  if (!words || words.length === 0) return [];

  // y 좌표 기준으로 같은 줄 묶기
  const lineGroups = [];
  const Y_THRESHOLD = 10; // 같은 줄로 인정할 y 차이

  for (const word of words) {
    if (!word.text || !word.text.trim()) continue;
    const bbox = word.bbox;
    const midY = (bbox.y0 + bbox.y1) / 2;

    let foundGroup = null;
    for (const group of lineGroups) {
      if (Math.abs(group.midY - midY) < Y_THRESHOLD) {
        foundGroup = group;
        break;
      }
    }

    if (foundGroup) {
      foundGroup.words.push(word);
      foundGroup.midY = (foundGroup.midY + midY) / 2;
    } else {
      lineGroups.push({ midY, words: [word] });
    }
  }

  // y 순서 정렬
  lineGroups.sort((a, b) => a.midY - b.midY);

  return lineGroups.map(group => {
    // x 순서로 단어 정렬
    group.words.sort((a, b) => a.bbox.x0 - b.bbox.x0);
    const text = group.words.map(w => w.text).join(' ').trim();
    const allBboxes = group.words.map(w => w.bbox);
    const bbox = {
      x0: Math.min(...allBboxes.map(b => b.x0)),
      y0: Math.min(...allBboxes.map(b => b.y0)),
      x1: Math.max(...allBboxes.map(b => b.x1)),
      y1: Math.max(...allBboxes.map(b => b.y1))
    };
    return { text, bbox };
  }).filter(l => l.text.length > 0);
}

// stdin 라인 단위 읽기
const rl = readline.createInterface({
  input: process.stdin,
  terminal: false
});

rl.on('line', async (line) => {
  let msg;
  try {
    msg = JSON.parse(line.trim());
  } catch {
    sendResult({ type: 'error', message: 'Invalid JSON input' });
    return;
  }

  if (msg.action === 'ocr') {
    const result = await runOCR(msg.imagePath, msg.lang || 'kor+eng');
    sendResult({ type: 'ocr_result', ...result });
  } else if (msg.action === 'exit') {
    if (ocrWorker) await ocrWorker.terminate();
    process.exit(0);
  } else if (msg.action === 'ping') {
    sendResult({ type: 'pong', ready: isReady });
  }
});

rl.on('close', async () => {
  if (ocrWorker) await ocrWorker.terminate();
  process.exit(0);
});

// 초기화 시작
initOCR();
