function clonePayload(payload) {
  return JSON.parse(JSON.stringify(payload || {}));
}

function isPhotoBatchablePayload(payload) {
  if (!payload || typeof payload !== 'object') return false;
  if (!Array.isArray(payload.photo) || payload.photo.length === 0) return false;
  if (payload.voice || payload.document) return false;
  return true;
}

function mergePhotoPayload(basePayload, nextPayload) {
  const merged = clonePayload(basePayload);
  const seenFileIds = new Set();
  const mergedPhotos = [];

  for (const candidate of [...(merged.photo || []), ...(nextPayload.photo || [])]) {
    if (!candidate || typeof candidate !== 'object') continue;
    const fileId = String(candidate.file_id || '').trim();
    if (!fileId || seenFileIds.has(fileId)) continue;
    seenFileIds.add(fileId);
    mergedPhotos.push({ ...candidate });
  }

  merged.photo = mergedPhotos;
  if (!merged.caption && typeof nextPayload.caption === 'string' && nextPayload.caption.trim()) {
    merged.caption = nextPayload.caption.trim();
  }
  if (!merged.text && typeof nextPayload.text === 'string' && nextPayload.text.trim()) {
    merged.text = nextPayload.text.trim();
  }
  if (!merged.reply_to_message && nextPayload.reply_to_message) {
    merged.reply_to_message = clonePayload(nextPayload.reply_to_message);
  }
  if (!merged.from && nextPayload.from) {
    merged.from = clonePayload(nextPayload.from);
  }
  return merged;
}

export class IncomingPhotoBatcher {
  constructor({ emit, quietWindowMs = 1500 } = {}) {
    if (typeof emit !== 'function') {
      throw new Error('emit callback is required');
    }
    this.emit = emit;
    this.quietWindowMs = Math.max(0, Number(quietWindowMs) || 0);
    this.pending = new Map();
  }

  _schedule(batchKey) {
    const entry = this.pending.get(batchKey);
    if (!entry) return;
    if (entry.timer) {
      clearTimeout(entry.timer);
    }
    entry.timer = setTimeout(() => {
      this.flush(batchKey);
    }, this.quietWindowMs);
    if (typeof entry.timer.unref === 'function') {
      entry.timer.unref();
    }
  }

  push(batchKey, payload) {
    if (!batchKey || !isPhotoBatchablePayload(payload)) {
      if (batchKey) {
        this.flush(batchKey);
      }
      this.emit(payload);
      return;
    }

    const existing = this.pending.get(batchKey);
    if (!existing) {
      this.pending.set(batchKey, {
        payload: clonePayload(payload),
        timer: null,
      });
      this._schedule(batchKey);
      return;
    }

    existing.payload = mergePhotoPayload(existing.payload, payload);
    this._schedule(batchKey);
  }

  flush(batchKey) {
    const entry = this.pending.get(batchKey);
    if (!entry) return false;
    if (entry.timer) {
      clearTimeout(entry.timer);
    }
    this.pending.delete(batchKey);
    this.emit(entry.payload);
    return true;
  }

  flushAll() {
    for (const batchKey of [...this.pending.keys()]) {
      this.flush(batchKey);
    }
  }
}

export { clonePayload, isPhotoBatchablePayload, mergePhotoPayload };
