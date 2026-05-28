const BIN_ID = "6a18206bddf5aa59f76f840f";
const MASTER_KEY = "$2a$10$f6wGmFyAQH13nZCkUQSn..kCCKbVD1tF5SFOCzFqhzj/tgKV/az3e";
const API_URL = `https://api.jsonbin.io/v3/b/${BIN_ID}`;

async function getDB() {
  const res = await fetch(API_URL + "/latest", { headers: { "X-Master-Key": MASTER_KEY } });
  const data = await res.json();
  return data.record || { keys: {} };
}

async function saveDB(db) {
  await fetch(API_URL, {
    method: "PUT",
    headers: { "X-Master-Key": MASTER_KEY, "Content-Type": "application/json" },
    body: JSON.stringify(db)
  });
}

exports.handler = async (event) => {
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
  };

  // Handle CORS preflight
  if (event.httpMethod === "OPTIONS") return { statusCode: 200, headers, body: "" };
  if (event.httpMethod !== "POST") return { statusCode: 405, headers, body: JSON.stringify({ valid: false, message: "Method Not Allowed" }) };

  // Parse body
  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, headers, body: JSON.stringify({ valid: false, message: "Body không hợp lệ" }) };
  }

  const { action, key, tokens } = body;
  if (!key) return { statusCode: 400, headers, body: JSON.stringify({ valid: false, message: "Thiếu Key" }) };

  const keyUpper = key.trim().toUpperCase();

  try {
    const db = await getDB();
    const keyData = db.keys && db.keys[keyUpper];

    if (!keyData) return { statusCode: 200, headers, body: JSON.stringify({ valid: false, message: "Key không tồn tại!" }) };
    if (keyData.expTs && Date.now() > keyData.expTs) return { statusCode: 200, headers, body: JSON.stringify({ valid: false, message: "Key đã hết hạn sử dụng!" }) };

    if (action === "validate") {
      return {
        statusCode: 200, headers,
        body: JSON.stringify({
          valid: true,
          exp: keyData.exp,
          expTs: keyData.expTs,
          tokens: keyData.tokens || { quest: [], hs_1: [], hs_2: [], hs_3: [] }
        })
      };
    }

    if (action === "update_tokens") {
      db.keys[keyUpper].tokens = tokens || { quest: [], hs_1: [], hs_2: [], hs_3: [] };
      await saveDB(db);
      return { statusCode: 200, headers, body: JSON.stringify({ success: true }) };
    }

    if (action === "add_log") {
      if (!db.keys[keyUpper].logs) db.keys[keyUpper].logs = [];
      db.keys[keyUpper].logs.push({ time: new Date().toLocaleTimeString("vi-VN"), msg: body.log });
      if (db.keys[keyUpper].logs.length > 10) db.keys[keyUpper].logs.shift(); // Chỉ giữ 10 dòng cuối
      await saveDB(db);
      return { statusCode: 200, headers, body: JSON.stringify({ success: true }) };
    }

    // action 'run_quest' không được xử lý ở backend → trả về lỗi rõ ràng thay vì crash
    return { statusCode: 400, headers, body: JSON.stringify({ valid: false, message: "Hành động không hợp lệ" }) };

  } catch (err) {
    return { statusCode: 500, headers, body: JSON.stringify({ valid: false, message: "Lỗi Server DB: " + err.message }) };
  }
};
