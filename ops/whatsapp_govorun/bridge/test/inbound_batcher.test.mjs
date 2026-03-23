import test from 'node:test';
import assert from 'node:assert/strict';

import {
  IncomingPhotoBatcher,
  isPhotoBatchablePayload,
  mergePhotoPayload
} from '../src/inbound_batcher.mjs';

test('isPhotoBatchablePayload only accepts photo-only payloads', () => {
  assert.equal(isPhotoBatchablePayload({ photo: [{ file_id: 'p1' }] }), true);
  assert.equal(isPhotoBatchablePayload({ photo: [{ file_id: 'p1' }], document: { file_id: 'd1' } }), false);
  assert.equal(isPhotoBatchablePayload({ text: 'hello' }), false);
});

test('mergePhotoPayload combines photo lists and preserves first caption', () => {
  const merged = mergePhotoPayload(
    {
      message_id: 1,
      caption: 'first caption',
      photo: [{ file_id: 'p1', file_size: 10 }]
    },
    {
      message_id: 2,
      caption: 'second caption',
      photo: [
        { file_id: 'p1', file_size: 10 },
        { file_id: 'p2', file_size: 20 }
      ]
    }
  );

  assert.equal(merged.caption, 'first caption');
  assert.deepEqual(
    merged.photo.map((item) => item.file_id),
    ['p1', 'p2']
  );
});

test('IncomingPhotoBatcher emits one merged payload for a photo batch', () => {
  const emitted = [];
  const batcher = new IncomingPhotoBatcher({
    emit: (payload) => emitted.push(payload),
    quietWindowMs: 50
  });

  batcher.push('chat-1::sender-1', {
    message_id: 1,
    photo: [{ file_id: 'p1', file_size: 10 }],
    caption: 'album caption'
  });
  batcher.push('chat-1::sender-1', {
    message_id: 2,
    photo: [{ file_id: 'p2', file_size: 20 }]
  });

  assert.equal(emitted.length, 0);
  assert.equal(batcher.flush('chat-1::sender-1'), true);
  assert.equal(emitted.length, 1);
  assert.equal(emitted[0].caption, 'album caption');
  assert.deepEqual(
    emitted[0].photo.map((item) => item.file_id),
    ['p1', 'p2']
  );
});

test('IncomingPhotoBatcher flushes pending photo batch before non-photo payload', () => {
  const emitted = [];
  const batcher = new IncomingPhotoBatcher({
    emit: (payload) => emitted.push(payload),
    quietWindowMs: 50
  });

  batcher.push('chat-1::sender-1', {
    message_id: 1,
    photo: [{ file_id: 'p1', file_size: 10 }]
  });
  batcher.push('chat-1::sender-1', {
    message_id: 2,
    text: 'follow-up text'
  });

  assert.equal(emitted.length, 2);
  assert.deepEqual(emitted[0].photo.map((item) => item.file_id), ['p1']);
  assert.equal(emitted[1].text, 'follow-up text');
});
