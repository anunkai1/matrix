window.SERVER3_CONTROL_PLANE_DATA = {
  "generatedAt": "2026-04-01T00:54:17.101556+10:00",
  "timezone": "Australia/Brisbane",
  "defaultRuntime": "architect",
  "summary": {
    "runtimeValue": "7 live",
    "runtimeCopy": "7 healthy, 0 degraded, 0 waiting, 0 offline",
    "approvalValue": "1 pending",
    "approvalCopy": "explicit human gates from live Server3 state",
    "jobValue": "8 tracked",
    "jobCopy": "timers, approvals, and operator playback in one surface",
    "hostValue": "load 5.61 / ram 49%",
    "hostCopy": "browser, timers, storage, and network summarized from the host",
    "currentPicture": [
      "01 Apr 2026 00:54 AEST",
      "snapshot file server3-control-plane-data.js",
      "1 approval item(s)"
    ],
    "surfaceBias": [
      "read-only live snapshot",
      "browser-local file:// compatible",
      "state color only"
    ],
    "chips": [
      {
        "tone": "ok",
        "label": "live status loaded"
      },
      {
        "tone": "busy",
        "label": "observer summary"
      },
      {
        "tone": "warn",
        "label": "1 approval item(s)"
      },
      {
        "tone": "busy",
        "label": "3 operator actions"
      },
      {
        "tone": "danger",
        "label": "storage remains continuity sensitive"
      }
    ]
  },
  "overview": {
    "bands": [
      {
        "title": "Nominal lane",
        "stateClass": "ok",
        "stateText": "healthy",
        "body": "7 selected runtimes match expected live posture."
      },
      {
        "title": "Approval lane",
        "stateClass": "warn",
        "stateText": "approval",
        "body": "1 operator approval item(s) currently surfaced."
      },
      {
        "title": "Watch lane",
        "stateClass": "danger",
        "stateText": "watch",
        "body": "expected inactive, got active"
      },
      {
        "title": "Offline lane",
        "stateClass": "ok",
        "stateText": "none",
        "body": "0 selected runtime(s) are currently offline."
      }
    ],
    "side": [
      {
        "label": "service footprint",
        "value": "7",
        "copy": "selected runtimes in the operator rail"
      },
      {
        "label": "operator gates",
        "value": "1",
        "copy": "explicit human approvals, not implicit risk"
      }
    ]
  },
  "activity": [
    {
      "time": "00:54:17",
      "title": "Optional UI layer is active",
      "channel": "host",
      "statusClass": "danger",
      "statusText": "watch",
      "copy": "expected inactive, got active"
    },
    {
      "time": "00:54:17",
      "title": "UI layer is active outside its default posture",
      "channel": "approval",
      "statusClass": "danger",
      "statusText": "operator review",
      "copy": "expected inactive, got active"
    },
    {
      "time": "00:54:15",
      "title": "Oracle recent service activity",
      "channel": "signal runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "2026-04-01 00:54:15,952 INFO 127.0.0.1 - \"GET /updates?offset=0&timeout=0 HTTP/1.1\" 200 -"
    },
    {
      "time": "21:15:04",
      "title": "Architect recent service activity",
      "channel": "telegram primary",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.request_processing_finished"
    },
    {
      "time": "20:31:04",
      "title": "Browser Brain recent service activity",
      "channel": "browser control surface",
      "statusClass": "busy",
      "statusText": "attached",
      "copy": "(1) Lydia Hallie ✨ on X: \"We're aware people are hitting usage limits in Claude C... | x session live; manual login tab open"
    },
    {
      "time": "20:02:14",
      "title": "Diary recent service activity",
      "channel": "capture runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.diary_batch_finished"
    }
  ],
  "playback": {
    "items": [
      {
        "time": "00:53:58",
        "title": "captured incident bundle",
        "channel": "incident",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "incident bundle via local. /home/architect/.local/state/server3-control-plane/bundles/incident-bundle-20260401T005358.json"
      },
      {
        "time": "00:53:58",
        "title": "refreshed control-plane snapshot",
        "channel": "snapshot",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "snapshot refresh via local. /home/architect/matrix/docs/server3-control-plane-data.json"
      },
      {
        "time": "00:53:56",
        "title": "viewed browser logs",
        "channel": "browser",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "runtime logs via local. server3-browser-brain.service"
      }
    ],
    "meta": [
      {
        "label": "recent operator actions",
        "value": "3"
      },
      {
        "label": "last actor path",
        "value": "local"
      },
      {
        "label": "last action",
        "value": "incident bundle"
      },
      {
        "label": "captured bundles",
        "value": "1"
      }
    ],
    "bundles": [
      {
        "label": "incident-bundle-20260401T005358.json",
        "value": "01 Apr 00:53 / 94 KiB"
      }
    ]
  },
  "approvals": [
    {
      "title": "UI layer is active outside its default posture",
      "riskClass": "danger",
      "riskText": "operator review",
      "body": "expected inactive, got active",
      "approveLabel": "accept for session",
      "rejectLabel": "turn desktop off"
    }
  ],
  "jobs": [
    {
      "title": "Approval queue",
      "tagClass": "warn",
      "tagText": "1 waiting",
      "body": "Pending actions are rendered here as operator work, not buried in prompt text."
    },
    {
      "title": "Observer summary",
      "tagClass": "busy",
      "tagText": "01 Apr 08:05",
      "body": "server3-runtime-observer.timer is active(waiting). Last trigger: 31 Mar 08:05."
    },
    {
      "title": "Routing drift check",
      "tagClass": "busy",
      "tagText": "01 Apr 06:15",
      "body": "server3-chat-routing-contract-check.timer is active(waiting). Last trigger: 31 Mar 06:15."
    },
    {
      "title": "State backup",
      "tagClass": "busy",
      "tagText": "01 Apr 05:00",
      "body": "server3-state-backup.timer is active(waiting). Last trigger: not scheduled."
    },
    {
      "title": "Receipt monitor",
      "tagClass": "busy",
      "tagText": "not scheduled",
      "body": "mavali-eth-receipt-monitor.timer is active(waiting). Last trigger: 01 Apr 00:35."
    }
  ],
  "floor": [
    {
      "title": "Disk posture",
      "stateClass": "warn",
      "stateText": "watch",
      "value": "18% used",
      "body": "/srv/external/server3-arr | 1402 GiB free of 1833 GiB",
      "statusLine": "backup disk: 7% used"
    },
    {
      "title": "Host health",
      "stateClass": "ok",
      "stateText": "nominal",
      "value": "load 5.61 / ram 49%",
      "body": "primary route nordlynx / 10.5.0.2",
      "statusLine": "host: server3"
    },
    {
      "title": "Key paths",
      "stateClass": "busy",
      "stateText": "live",
      "value": "/data/downloads",
      "body": "missing | path unavailable",
      "statusLine": "canonical media namespace is /data/downloads and /data/media/..."
    },
    {
      "title": "Schedules",
      "stateClass": "busy",
      "stateText": "queued",
      "value": "Observer summary, Routing drift check, State backup",
      "body": "Visible timers stay on the floor so continuity work is never hidden behind another tool.",
      "statusLine": "next: 01 Apr 08:05"
    }
  ],
  "runtimes": [
    {
      "key": "architect",
      "name": "Architect",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "Telegram primary",
      "operatorNote": "owner-facing runtime",
      "summary": "Main Telegram and CLI runtime for Server3 operations.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-architect-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/architect/matrix"
        },
        {
          "label": "owner",
          "value": "architect"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-architect-bridge.service",
          "value": "21:15:04 bridge.request_processing_finished"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Primary operator entry point on Server3."
        },
        {
          "label": "change control",
          "value": "persistent repo edits still require commit and push proof"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-architect-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/telegram-architect-bridge.md"
        },
        {
          "label": "policy",
          "value": "ARCHITECT_INSTRUCTION.md"
        }
      ],
      "unitNames": [
        "telegram-architect-bridge.service"
      ],
      "auditTrail": [],
      "browserLane": null
    },
    {
      "key": "tank",
      "name": "Tank",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "Telegram sibling",
      "operatorNote": "isolated Telegram runtime",
      "summary": "Sibling Telegram assistant with isolated runtime state.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-tank-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/tank/tankbot"
        },
        {
          "label": "owner",
          "value": "tank"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-tank-bridge.service",
          "value": "23:42:44 bridge.telegram_api_retry_succeeded | getUpdates"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Uses the shared bridge pattern with its own workspace and memory."
        },
        {
          "label": "identity",
          "value": "preserve isolated runtime root and Joplin profile"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-tank-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runtime_docs/tank"
        },
        {
          "label": "runbook",
          "value": "ops/runtime_personas/check_runtime_repo_links.sh"
        }
      ],
      "unitNames": [
        "telegram-tank-bridge.service"
      ],
      "auditTrail": [],
      "browserLane": null
    },
    {
      "key": "diary",
      "name": "Diary",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "capture runtime",
      "operatorNote": "capture-focused sibling",
      "summary": "Dedicated Telegram diary assistant for low-friction text, voice, and photo capture.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-diary-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/diary/diarybot"
        },
        {
          "label": "owner",
          "value": "diary"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-diary-bridge.service",
          "value": "20:02:14 bridge.diary_batch_finished"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Runs the shared Telegram bridge with its own runtime root, AGENTS.md, and diary-oriented operating docs."
        },
        {
          "label": "delivery",
          "value": "capture routing should stay friction-light"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-diary-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runtime_docs/diary"
        },
        {
          "label": "policy",
          "value": "docs/runtime_docs/diary/DIARY_INSTRUCTION.md"
        }
      ],
      "unitNames": [
        "telegram-diary-bridge.service"
      ],
      "auditTrail": [],
      "browserLane": null
    },
    {
      "key": "govorun",
      "name": "Govorun",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "WhatsApp runtime",
      "operatorNote": "dual transport + bridge",
      "summary": "WhatsApp transport/API runtime used by the Govorun bridge.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "whatsapp-govorun-bridge.service, govorun-whatsapp-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/govorun/whatsapp-govorun/app"
        },
        {
          "label": "owner",
          "value": "govorun"
        },
        {
          "label": "live state",
          "value": "active / active"
        }
      ],
      "recentJobs": [
        {
          "label": "whatsapp-govorun-bridge.service",
          "value": "00:28:14 Started whatsapp-govorun-bridge.service - WhatsApp Govorun Bridge (Codex)."
        },
        {
          "label": "govorun-whatsapp-bridge.service",
          "value": "17:51:20 bridge.request_ignored | prefix_required"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Node transport sidecar for the Python Govorun bridge."
        },
        {
          "label": "routing contract",
          "value": "daily contract drift timer should stay green"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u whatsapp-govorun-bridge.service -u govorun-whatsapp-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runbooks/whatsapp-govorun-operations.md"
        },
        {
          "label": "guard",
          "value": "ops/chat-routing/validate_chat_routing_contract.py"
        }
      ],
      "unitNames": [
        "whatsapp-govorun-bridge.service",
        "govorun-whatsapp-bridge.service"
      ],
      "auditTrail": [],
      "browserLane": null
    },
    {
      "key": "oracle",
      "name": "Oracle",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "Signal runtime",
      "operatorNote": "transport + bridge",
      "summary": "Signal transport sidecar used by the Oracle bridge.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "signal-oracle-bridge.service, oracle-signal-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/oracle/signal-oracle/app"
        },
        {
          "label": "owner",
          "value": "oracle"
        },
        {
          "label": "live state",
          "value": "active / active"
        }
      ],
      "recentJobs": [
        {
          "label": "signal-oracle-bridge.service",
          "value": "00:54:15 2026-04-01 00:54:15,952 INFO 127.0.0.1 - \"GET /updates?offset=0&timeout=0 HTTP/1.1\" 200 -"
        },
        {
          "label": "oracle-signal-bridge.service",
          "value": "21:07:01 bridge.request_processing_finished"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Transport sidecar for the Oracle Signal runtime."
        },
        {
          "label": "voice path",
          "value": "keep local transcription runtime separate from transport health"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u signal-oracle-bridge.service -u oracle-signal-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runbooks/oracle-signal-operations.md"
        },
        {
          "label": "voice",
          "value": "ops/telegram-voice/transcribe_voice.sh"
        }
      ],
      "unitNames": [
        "signal-oracle-bridge.service",
        "oracle-signal-bridge.service"
      ],
      "auditTrail": [],
      "browserLane": null
    },
    {
      "key": "mavali",
      "name": "Mavali ETH",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "venue operations runtime",
      "operatorNote": "owner-bound wallet runtime",
      "summary": "Wallet-first Ethereum mainnet runtime with deterministic wallet actions and Codex fallback for non-wallet prompts.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-mavali-eth-bridge.service, mavali-eth-receipt-monitor.timer"
        },
        {
          "label": "workspace",
          "value": "/home/mavali_eth/mavali_ethbot"
        },
        {
          "label": "owner",
          "value": "mavali_eth"
        },
        {
          "label": "live state",
          "value": "mixed"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-mavali-eth-bridge.service",
          "value": "15:16:35 bridge.request_processing_finished"
        },
        {
          "label": "mavali-eth-receipt-monitor.timer",
          "value": "17:17:45 Started mavali-eth-receipt-monitor.timer - Poll for confirmed inbound ETH for mavali_eth."
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Runs the shared Telegram bridge with the mavali_eth deterministic wallet engine plus Codex fallback for non-wallet prompts."
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-mavali-eth-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runbooks/mavali-eth-operations.md"
        },
        {
          "label": "guard",
          "value": "bridge-side pending-action guard"
        }
      ],
      "unitNames": [
        "telegram-mavali-eth-bridge.service",
        "mavali-eth-receipt-monitor.timer"
      ],
      "auditTrail": [],
      "browserLane": null
    },
    {
      "key": "browser",
      "name": "Browser Brain",
      "stateClass": "busy",
      "stateText": "attached",
      "role": "browser control surface",
      "operatorNote": "existing-session browser runtime",
      "summary": "Dedicated local browser-control service for structured automation against a managed Brave profile.",
      "actions": [
        "show browser lane",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "server3-browser-brain.service"
        },
        {
          "label": "workspace",
          "value": "/home/browser_brain/browserbrain"
        },
        {
          "label": "owner",
          "value": "browser_brain"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "20:31:04 snapshot",
          "value": "261 elements | snap-cbe972f8"
        },
        {
          "label": "20:31:04 snapshot",
          "value": "235 elements | snap-adee1db6"
        },
        {
          "label": "20:31:03 snapshot",
          "value": "168 elements | snap-593918bc"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Separate from the TV desktop/browser flow and intended for loopback-only local callers."
        },
        {
          "label": "recovery path",
          "value": "existing-session path available"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u server3-browser-brain.service"
        },
        {
          "label": "summary",
          "value": "SERVER3_SUMMARY.md"
        },
        {
          "label": "policy",
          "value": "existing_session is canonical"
        }
      ],
      "unitNames": [
        "server3-browser-brain.service"
      ],
      "auditTrail": [
        {
          "label": "01 Apr 00:53 / runtime logs",
          "value": "ok via local | server3-browser-brain.service"
        }
      ],
      "browserLane": {
        "state": [
          {
            "label": "connection",
            "value": "existing_session / running"
          },
          {
            "label": "auth posture",
            "value": "x session live; manual login tab open"
          },
          {
            "label": "manual takeover",
            "value": "server3 (1) Evan Luthra on X: \"POV: Sam Altman refreshing Anthropic’s X account e..."
          },
          {
            "label": "tab footprint",
            "value": "14 live tabs / x.com x11, example.com x1"
          }
        ],
        "targets": [
          {
            "label": "current target",
            "value": "(1) Lydia Hallie ✨ on X: \"We're aware people are hitting usage limits in Claude C..."
          },
          {
            "label": "tab-e9e43e68",
            "value": "(1) QuarkQ (@QuarkQ143033) / X"
          },
          {
            "label": "tab-5a0f810f",
            "value": "(1) Elon Musk on X: \"Cool, well Grok will get even better every week!\" / X"
          },
          {
            "label": "tab-adc826c0",
            "value": "(1) QuarkQ (@QuarkQ143033) / X"
          },
          {
            "label": "tab-80ad9b7d",
            "value": "(1) Explore / X"
          }
        ],
        "captures": [
          {
            "label": "20260322T114237Z-smo_vz_status_viewport.png",
            "value": "22 Mar 21:42 / 308 KiB"
          },
          {
            "label": "20260322T114217Z-smo_vz_status.png",
            "value": "22 Mar 21:42 / 1873 KiB"
          },
          {
            "label": "20260322T084947Z-compose-tab.png",
            "value": "22 Mar 18:49 / 1098 KiB"
          }
        ],
        "activity": [
          {
            "label": "20:31:04 snapshot",
            "value": "261 elements | snap-cbe972f8"
          },
          {
            "label": "20:31:04 snapshot",
            "value": "235 elements | snap-adee1db6"
          },
          {
            "label": "20:31:03 snapshot",
            "value": "168 elements | snap-593918bc"
          },
          {
            "label": "20:31:03 snapshot",
            "value": "138 elements | snap-c5ede80c"
          }
        ],
        "summary": {
          "current_target": "(1) Lydia Hallie ✨ on X: \"We're aware people are hitting usage limits in Claude C...",
          "tab_count": 14,
          "auth_posture": "x session live; manual login tab open",
          "manual_takeover": "visible tv helper open",
          "capture_dir": "/var/lib/server3-browser-brain/captures",
          "started_at": "2026-03-22T08:48:16.273908+00:00"
        }
      }
    }
  ]
};
