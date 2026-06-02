const express = require("express");
const morgan = require("morgan");
const dotenv = require("dotenv");
const path = require("path");
const fs = require("fs");
const crypto = require("crypto");
const Database = require("better-sqlite3");

dotenv.config();

const app = express();
const PORT = Number(process.env.PORT || 4021);
const APP_PASSWORD = String(process.env.APP_PASSWORD || "").trim();
const SESSION_TTL_DAYS = Math.max(1, Number(process.env.SESSION_TTL_DAYS || 30));
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, "data");
const SITE_URL = process.env.SITE_URL || "https://mavali.top/projects/Foodle/";

const DEFAULT_MEMBERS = [
  { id: "family", label: "Family", color: "#1768ac" },
];

const DEFAULT_TRACKERS = [
  { id: "sugar-free", label: "Sugar-free", code: "SF", color: "#36b37e" },
  { id: "carb-light", label: "Carb-light", code: "CL", color: "#7c5cff" },
  { id: "dairy-free", label: "Dairy-free", code: "DF", color: "#4da3ff" },
  { id: "did-not-overeat", label: "Overeat-free", code: "OEF", color: "#f59e0b" },
  { id: "red-meat-free", label: "Red meat-free", code: "RMF", color: "#14b8a6" },
  { id: "exercise", label: "Exercise", code: "EX", color: "#f97316" },
  { id: "coffee", label: "Coffee", code: "CF", color: "#8b5a2b" },
  { id: "fasting", label: "Fasting", code: "FS", color: "#52c7b8" },
];

function parseListEnv(name, fallback, valueValidator) {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      throw new Error(`${name} must be a non-empty JSON array`);
    }
    return parsed.map((item, index) => valueValidator(item, index));
  } catch (error) {
    console.warn(`Failed to parse ${name}: ${error.message}. Using defaults.`);
    return fallback;
  }
}

function validateId(value, fallback) {
  const normalized = String(value || fallback || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!normalized) {
    throw new Error("id must contain letters or numbers");
  }
  return normalized;
}

function validateMember(item, index) {
  return {
    id: validateId(item.id, `member-${index + 1}`),
    label: String(item.label || `Member ${index + 1}`).trim(),
    color: String(item.color || "#4f7cff").trim(),
  };
}

function validateCode(value, fallback) {
  const normalized = String(value || fallback || "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "");
  if (!normalized) {
    throw new Error("code must contain letters or numbers");
  }
  return normalized;
}

function validateTracker(item, index) {
  return {
    id: validateId(item.id, `tracker-${index + 1}`),
    label: String(item.label || `Tracker ${index + 1}`).trim(),
    code: validateCode(item.code, `T${index + 1}`),
    color: String(item.color || "#4f7cff").trim(),
  };
}

const MEMBERS = parseListEnv("MEMBERS_JSON", DEFAULT_MEMBERS, validateMember);
const TRACKERS = parseListEnv("TRACKERS_JSON", DEFAULT_TRACKERS, validateTracker);
const MEMBER_IDS = new Set(MEMBERS.map((item) => item.id));
const TRACKER_IDS = new Set(TRACKERS.map((item) => item.id));
const TOTAL_COMBINATIONS = MEMBERS.length * TRACKERS.length;

if (!APP_PASSWORD) {
  console.error("APP_PASSWORD must be set in the live .env file.");
  process.exit(1);
}

fs.mkdirSync(DATA_DIR, { recursive: true });
const DB_PATH = path.join(DATA_DIR, "foodle.sqlite");
const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");

db.exec(`
  CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    member_id TEXT NOT NULL,
    tracker_id TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '' ,
    updated_at TEXT NOT NULL,
    UNIQUE(entry_date, member_id, tracker_id)
  );

  CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
  );
`);

const statements = {
  insertSession: db.prepare(`
    INSERT INTO sessions (token, label, expires_at, created_at)
    VALUES (@token, @label, @expires_at, @created_at)
  `),
  deleteSession: db.prepare(`DELETE FROM sessions WHERE token = ?`),
  deleteExpiredSessions: db.prepare(`DELETE FROM sessions WHERE expires_at <= ?`),
  selectSession: db.prepare(`
    SELECT token, label, expires_at, created_at
    FROM sessions
    WHERE token = ? AND expires_at > ?
  `),
  upsertEntry: db.prepare(`
    INSERT INTO entries (entry_date, member_id, tracker_id, done, note, updated_at)
    VALUES (@entry_date, @member_id, @tracker_id, @done, @note, @updated_at)
    ON CONFLICT(entry_date, member_id, tracker_id) DO UPDATE SET
      done = excluded.done,
      note = excluded.note,
      updated_at = excluded.updated_at
  `),
  selectEntriesForRange: db.prepare(`
    SELECT entry_date, member_id, tracker_id, done, note, updated_at
    FROM entries
    WHERE entry_date >= ? AND entry_date <= ?
    ORDER BY entry_date ASC, member_id ASC, tracker_id ASC
  `),
};

function nowIso() {
  return new Date().toISOString();
}

function todayIso() {
  return formatDateForLocal(new Date());
}

function formatDateForLocal(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function normalizeDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) {
    throw new Error("date must use YYYY-MM-DD");
  }
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error("date is invalid");
  }
  return formatDateForLocal(parsed);
}

function normalizeMonth(value) {
  if (!value) {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  }
  if (!/^\d{4}-\d{2}$/.test(String(value))) {
    throw new Error("month must use YYYY-MM");
  }
  return value;
}

function getMonthBounds(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  const start = new Date(year, month - 1, 1);
  const end = new Date(year, month, 0);
  return {
    start: formatDateForLocal(start),
    end: formatDateForLocal(end),
  };
}

function getDefaultSelectedDate(monthKey) {
  const today = todayIso();
  if (today.startsWith(`${monthKey}-`)) {
    return today;
  }
  return `${monthKey}-01`;
}

function parseCookies(header) {
  return String(header || "")
    .split(";")
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .reduce((acc, item) => {
      const separator = item.indexOf("=");
      if (separator === -1) {
        return acc;
      }
      const key = item.slice(0, separator).trim();
      const value = item.slice(separator + 1).trim();
      acc[key] = decodeURIComponent(value);
      return acc;
    }, {});
}

function setSessionCookie(res, token) {
  const maxAge = SESSION_TTL_DAYS * 24 * 60 * 60;
  res.setHeader(
    "Set-Cookie",
    `foodle_session=${encodeURIComponent(token)}; Max-Age=${maxAge}; Path=/; HttpOnly; SameSite=Lax; Secure`
  );
}

function clearSessionCookie(res) {
  res.setHeader(
    "Set-Cookie",
    "foodle_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax; Secure"
  );
}

function buildEntryMap(rows) {
  const map = new Map();
  for (const row of rows) {
    const key = `${row.entry_date}|${row.member_id}|${row.tracker_id}`;
    map.set(key, {
      date: row.entry_date,
      memberId: row.member_id,
      trackerId: row.tracker_id,
      done: Boolean(row.done),
      note: row.note || "",
      updatedAt: row.updated_at,
    });
  }
  return map;
}

function buildMonthDays(monthKey, entryRows) {
  const { start, end } = getMonthBounds(monthKey);
  const map = buildEntryMap(entryRows);
  const days = [];
  const cursor = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);

  while (cursor <= endDate) {
    const date = formatDateForLocal(cursor);
    let completed = 0;
    const byMember = {};
    const trackers = TRACKERS.map((tracker) => ({
      trackerId: tracker.id,
      label: tracker.label,
      code: tracker.code,
      color: tracker.color,
      doneCount: 0,
      total: MEMBERS.length,
      ratio: 0,
      active: false,
    }));

    for (const member of MEMBERS) {
      let memberCompleted = 0;
      for (const [index, tracker] of TRACKERS.entries()) {
        const row = map.get(`${date}|${member.id}|${tracker.id}`);
        if (row && row.done) {
          completed += 1;
          memberCompleted += 1;
          trackers[index].doneCount += 1;
        }
      }
      byMember[member.id] = memberCompleted;
    }

    for (const tracker of trackers) {
      tracker.ratio = tracker.total ? Number((tracker.doneCount / tracker.total).toFixed(3)) : 0;
      tracker.active = tracker.doneCount > 0;
    }

    days.push({
      date,
      completed,
      total: TOTAL_COMBINATIONS,
      ratio: TOTAL_COMBINATIONS ? Number((completed / TOTAL_COMBINATIONS).toFixed(3)) : 0,
      byMember,
      trackers,
    });

    cursor.setDate(cursor.getDate() + 1);
  }

  return days;
}

function getTrackerStreak(map, memberId, trackerId, endDate) {
  let streak = 0;
  const cursor = new Date(`${endDate}T00:00:00`);
  while (true) {
    const date = formatDateForLocal(cursor);
    const row = map.get(`${date}|${memberId}|${trackerId}`);
    if (!row || !row.done) {
      break;
    }
    streak += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

function buildSelectedDay(date, entryRows) {
  const map = buildEntryMap(entryRows);
  
  const members = MEMBERS.map((member) => ({
    ...member,
    completed: 0,
    total: TRACKERS.length,
    trackers: TRACKERS.map((tracker) => {
      const row = map.get(`${date}|${member.id}|${tracker.id}`);
      const done = Boolean(row && row.done);
      if (done) {
        member.completed += 1;
      }
      return {
        ...tracker,
        done,
        streak: getTrackerStreak(map, member.id, tracker.id, date),
        note: row ? row.note : "",
        updatedAt: row ? row.updatedAt : null,
      };
    }),
  }));

  const completed = members.reduce((sum, item) => sum + item.completed, 0);
  return {
    date,
    completed,
    total: TOTAL_COMBINATIONS,
    ratio: TOTAL_COMBINATIONS ? Number((completed / TOTAL_COMBINATIONS).toFixed(3)) : 0,
    members,
  };
}

function getStreak(monthDays) {
  let best = 0;
  let current = 0;
  for (const day of monthDays) {
    if (day.completed > 0) {
      current += 1;
      if (current > best) {
        best = current;
      }
    } else {
      current = 0;
    }
  }
  return best;
}

function getCurrentStreak(monthDays, selectedDate) {
  let current = 0;
  for (let index = monthDays.length - 1; index >= 0; index -= 1) {
    const day = monthDays[index];
    if (day.date > selectedDate) {
      continue;
    }
    if (day.completed > 0) {
      current += 1;
    } else {
      break;
    }
  }
  return current;
}

function getTrackerDayActive(day, trackerId) {
  const tracker = (day.trackers || []).find((item) => item.trackerId === trackerId);
  return Boolean(tracker && tracker.active);
}

function getTrackerBestStreak(monthDays, trackerId) {
  let best = 0;
  let current = 0;
  for (const day of monthDays) {
    if (getTrackerDayActive(day, trackerId)) {
      current += 1;
      if (current > best) {
        best = current;
      }
    } else {
      current = 0;
    }
  }
  return best;
}

function getTrackerCurrentStreak(monthDays, trackerId, selectedDate) {
  let current = 0;
  for (let index = monthDays.length - 1; index >= 0; index -= 1) {
    const day = monthDays[index];
    if (day.date > selectedDate) {
      continue;
    }
    if (getTrackerDayActive(day, trackerId)) {
      current += 1;
    } else {
      break;
    }
  }
  return current;
}

function getTrackerCurrentStreakFromMap(map, trackerId, endDate) {
  let streak = 0;
  let cursor = new Date(`${endDate}T00:00:00`);
  while (true) {
    const date = formatDateForLocal(cursor);
    // Check all members for this date+tracker
    let anyDone = false;
    for (const member of MEMBERS) {
      const row = map.get(`${date}|${member.id}|${trackerId}`);
      if (row && row.done) {
        anyDone = true;
        break;
      }
    }
    if (!anyDone) break;
    streak += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

function getTrackerBestStreakFromMap(map, trackerId, endDate) {
  let best = 0;
  let current = 0;
  // Scan from beginning to end
  const cursor = new Date(`${endDate}T00:00:00`);
  cursor.setFullYear(cursor.getFullYear() - 5); // go back 5 years max
  const floor = new Date(`${endDate}T00:00:00`);
  
  while (cursor <= floor) {
    const date = formatDateForLocal(cursor);
    let anyDone = false;
    for (const member of MEMBERS) {
      const row = map.get(`${date}|${member.id}|${trackerId}`);
      if (row && row.done) {
        anyDone = true;
        break;
      }
    }
    if (anyDone) {
      current += 1;
      if (current > best) best = current;
    } else {
      current = 0;
    }
    cursor.setDate(cursor.getDate() + 1);
  }
  return best;
}

function serializeState({ monthKey, selectedDate }) {
  const { start, end } = getMonthBounds(monthKey);
  const entryRows = statements.selectEntriesForRange.all(start, end);
  const monthDays = buildMonthDays(monthKey, entryRows);
  
  // Query all entries from beginning for cross-month streak computation
  const allEntryRows = statements.selectEntriesForRange.all("2020-01-01", end);
  const allEntryMap = buildEntryMap(allEntryRows);
  
  const streakTrackerIds = ["sugar-free", "did-not-overeat", "red-meat-free", "exercise"];
  const streakTrackers = TRACKERS.filter((tracker) => streakTrackerIds.includes(tracker.id)).map((tracker) => ({
    id: tracker.id,
    label: tracker.label,
    code: tracker.code,
    bestStreak: getTrackerBestStreakFromMap(allEntryMap, tracker.id, end),
    currentStreak: getTrackerCurrentStreakFromMap(allEntryMap, tracker.id, selectedDate),
  }));
  const bestStreak = streakTrackers.reduce((max, item) => Math.max(max, item.bestStreak), 0);
  const currentStreak = streakTrackers.reduce((max, item) => Math.max(max, item.currentStreak), 0);
  return {
    today: todayIso(),
    month: {
      key: monthKey,
      days: monthDays,
      streak: getStreak(monthDays),
      bestStreak,
      currentStreak,
      streakTrackers,
      completed: monthDays.reduce((sum, item) => sum + item.completed, 0),
      total: monthDays.length * TOTAL_COMBINATIONS,
    },
    selected: buildSelectedDay(selectedDate, entryRows),
    config: {
      siteUrl: SITE_URL,
      members: MEMBERS,
      trackers: TRACKERS,
    },
  };
}

function requireAuth(req, res, next) {
  statements.deleteExpiredSessions.run(nowIso());
  const cookies = parseCookies(req.headers.cookie);
  const token = cookies.foodle_session;
  if (!token) {
    return res.status(401).json({ error: "Authentication required" });
  }
  const session = statements.selectSession.get(token, nowIso());
  if (!session) {
    clearSessionCookie(res);
    return res.status(401).json({ error: "Session expired" });
  }
  req.session = session;
  return next();
}

app.disable("x-powered-by");
app.use(morgan("combined"));
app.use(express.json({ limit: "1mb" }));

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: "foodle-api",
    dbPath: DB_PATH,
    today: todayIso(),
  });
});

app.post("/api/auth/login", (req, res) => {
  const password = String(req.body && req.body.password ? req.body.password : "");
  if (!password || password !== APP_PASSWORD) {
    return res.status(401).json({ error: "Wrong password" });
  }

  const token = crypto.randomBytes(24).toString("hex");
  const createdAt = nowIso();
  const expiresAt = new Date(Date.now() + SESSION_TTL_DAYS * 24 * 60 * 60 * 1000).toISOString();
  statements.insertSession.run({
    token,
    label: "family",
    expires_at: expiresAt,
    created_at: createdAt,
  });
  setSessionCookie(res, token);
  return res.json({ ok: true });
});

app.post("/api/auth/logout", requireAuth, (req, res) => {
  statements.deleteSession.run(req.session.token);
  clearSessionCookie(res);
  return res.json({ ok: true });
});

app.get("/api/bootstrap", requireAuth, (req, res) => {
  try {
    const monthKey = normalizeMonth(req.query.month);
    const selectedDate = req.query.date ? normalizeDate(req.query.date) : getDefaultSelectedDate(monthKey);
    return res.json(serializeState({ monthKey, selectedDate }));
  } catch (error) {
    return res.status(400).json({ error: error.message });
  }
});

app.post("/api/entries", requireAuth, (req, res) => {
  try {
    const date = normalizeDate(req.body.date);
    const memberId = validateId(req.body.memberId);
    const trackerId = validateId(req.body.trackerId);
    const done = Boolean(req.body.done);
    const note = String(req.body.note || "").slice(0, 500);

    if (!MEMBER_IDS.has(memberId)) {
      throw new Error("Unknown memberId");
    }
    if (!TRACKER_IDS.has(trackerId)) {
      throw new Error("Unknown trackerId");
    }

    statements.upsertEntry.run({
      entry_date: date,
      member_id: memberId,
      tracker_id: trackerId,
      done: done ? 1 : 0,
      note,
      updated_at: nowIso(),
    });

    const monthKey = date.slice(0, 7);
    return res.json({
      ok: true,
      ...serializeState({ monthKey, selectedDate: date }),
    });
  } catch (error) {
    return res.status(400).json({ error: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Foodle API listening on ${PORT}`);
});
