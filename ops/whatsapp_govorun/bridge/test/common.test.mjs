import test from 'node:test';
import assert from 'node:assert/strict';

import {
  extractReplyContextFromBaileysMessage,
  extractReplyContextInfoFromBaileysMessage
} from '../src/common.mjs';

test('extractReplyContextInfoFromBaileysMessage preserves quoted image payload', () => {
  const msg = {
    message: {
      extendedTextMessage: {
        text: '@говорун what is this?',
        contextInfo: {
          stanzaId: 'wa-quoted-1',
          participant: '61400000000@s.whatsapp.net',
          quotedMessage: {
            imageMessage: {
              mimetype: 'image/jpeg',
              caption: 'Old caption',
              url: 'https://example.invalid/image'
            }
          }
        }
      }
    }
  };

  const result = extractReplyContextInfoFromBaileysMessage(msg);

  assert.ok(result);
  assert.equal(result.reply.wa_message_id, 'wa-quoted-1');
  assert.equal(result.reply.from.username, '61400000000@s.whatsapp.net');
  assert.equal(result.reply.text, 'Old caption');
  assert.equal(result.quotedMessage.imageMessage.mimetype, 'image/jpeg');
});

test('extractReplyContextInfoFromBaileysMessage keeps media-only quote context', () => {
  const msg = {
    message: {
      extendedTextMessage: {
        text: '@говорун analyse this',
        contextInfo: {
          quotedMessage: {
            imageMessage: {
              mimetype: 'image/jpeg',
              url: 'https://example.invalid/image'
            }
          }
        }
      }
    }
  };

  const result = extractReplyContextInfoFromBaileysMessage(msg);

  assert.ok(result);
  assert.deepEqual(result.reply, {});
  assert.equal(result.quotedMessage.imageMessage.mimetype, 'image/jpeg');
});

test('extractReplyContextFromBaileysMessage returns plain reply metadata only', () => {
  const msg = {
    message: {
      extendedTextMessage: {
        text: '@говорун what about this?',
        contextInfo: {
          stanzaId: 'wa-quoted-2',
          participant: '61400000001@s.whatsapp.net',
          quotedMessage: {
            conversation: 'Quoted text'
          }
        }
      }
    }
  };

  assert.deepEqual(extractReplyContextFromBaileysMessage(msg), {
    text: 'Quoted text',
    wa_message_id: 'wa-quoted-2',
    from: { username: '61400000001@s.whatsapp.net' }
  });
});
