window.SERVER3_CONTROL_PLANE_DATA = {
  "generatedAt": "2026-04-24T07:00:15.278883+10:00",
  "timezone": "Australia/Brisbane",
  "defaultRuntime": "architect",
  "summary": {
    "runtimeValue": "7 live",
    "runtimeCopy": "6 healthy, 1 degraded, 0 waiting, 0 offline",
    "approvalValue": "0 pending",
    "approvalCopy": "explicit human gates from live Server3 state",
    "jobValue": "12 tracked",
    "jobCopy": "timers, approvals, and operator playback in one surface",
    "hostValue": "load 0.72 / ram 12%",
    "hostCopy": "browser, timers, storage, and network summarized from the host",
    "currentPicture": [
      "24 Apr 2026 07:00 AEST",
      "snapshot file server3-control-plane-data.js",
      "0 approval item(s)"
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
        "label": "0 approval item(s)"
      },
      {
        "tone": "busy",
        "label": "8 operator actions"
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
        "body": "6 selected runtimes match expected live posture."
      },
      {
        "title": "Approval lane",
        "stateClass": "ok",
        "stateText": "clear",
        "body": "0 operator approval item(s) currently surfaced."
      },
      {
        "title": "Watch lane",
        "stateClass": "ok",
        "stateText": "clear",
        "body": "No selected runtime is currently off its default expected posture."
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
        "value": "0",
        "copy": "explicit human approvals, not implicit risk"
      }
    ]
  },
  "activity": [
    {
      "time": "07:00:15",
      "title": "Oracle recent service activity",
      "channel": "signal runtime",
      "statusClass": "danger",
      "statusText": "degraded",
      "copy": "2026-04-24 07:00:15,792 WARNING Signal event stream failed: <urlopen error [Errno 111] Connection refused>"
    },
    {
      "time": "07:00:15",
      "title": "Architect recent service activity",
      "channel": "telegram primary",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.interrupted_requests_processed"
    },
    {
      "time": "07:00:15",
      "title": "Diary recent service activity",
      "channel": "capture runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.interrupted_requests_processed"
    },
    {
      "time": "07:00:15",
      "title": "Tank recent service activity",
      "channel": "telegram sibling",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.interrupted_requests_processed"
    },
    {
      "time": "07:00:15",
      "title": "Mavali ETH recent service activity",
      "channel": "venue operations runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.interrupted_requests_processed"
    },
    {
      "time": "07:00:14",
      "title": "Browser Brain recent service activity",
      "channel": "browser control surface",
      "statusClass": "busy",
      "statusText": "attached",
      "copy": "no live browser target | no explicit auth cue"
    }
  ],
  "playback": {
    "items": [
      {
        "time": "21:42:58",
        "title": "SignalTube rescan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube rescan via token. signaltube-lab-rescan.service"
      },
      {
        "time": "21:39:40",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. show me some videos from the last 3 days on cryptocurrency"
      },
      {
        "time": "21:31:48",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to watch about science"
      },
      {
        "time": "21:01:28",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to see videos about philosophy"
      },
      {
        "time": "20:48:17",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via local. I want to see videos about AI news, but not from MSM"
      },
      {
        "time": "20:39:35",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to see videos about AI news, but not from MSM"
      },
      {
        "time": "19:27:59",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to see videos about AI news, but not from MSM"
      },
      {
        "time": "19:12:56",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via local. That is a bit too much mainstream news, can you remove mainstream news"
      }
    ],
    "meta": [
      {
        "label": "recent operator actions",
        "value": "8"
      },
      {
        "label": "last actor path",
        "value": "token"
      },
      {
        "label": "last action",
        "value": "signaltube rescan"
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
  "approvals": [],
  "jobs": [
    {
      "title": "Observer summary",
      "tagClass": "busy",
      "tagText": "24 Apr 08:05",
      "body": "server3-runtime-observer.timer is active(waiting). Last trigger: 23 Apr 08:05."
    },
    {
      "title": "Routing drift check",
      "tagClass": "busy",
      "tagText": "25 Apr 06:15",
      "body": "server3-chat-routing-contract-check.timer is active(waiting). Last trigger: 24 Apr 06:15."
    },
    {
      "title": "State backup",
      "tagClass": "busy",
      "tagText": "01 May 05:00",
      "body": "server3-state-backup.timer is active(waiting). Last trigger: 01 Apr 05:00."
    },
    {
      "title": "Receipt monitor",
      "tagClass": "busy",
      "tagText": "not scheduled",
      "body": "mavali-eth-receipt-monitor.timer is active(waiting). Last trigger: 24 Apr 06:54."
    }
  ],
  "floor": [
    {
      "title": "Disk posture",
      "stateClass": "warn",
      "stateText": "watch",
      "value": "32% used",
      "body": "/srv/external/server3-arr | 1162 GiB free of 1833 GiB",
      "statusLine": "backup disk: 7% used"
    },
    {
      "title": "Host health",
      "stateClass": "ok",
      "stateText": "nominal",
      "value": "load 0.72 / ram 12%",
      "body": "primary route nordlynx / 10.5.0.2",
      "statusLine": "host: server3"
    },
    {
      "title": "Key paths",
      "stateClass": "busy",
      "stateText": "live",
      "value": "/data/downloads",
      "body": "11% used | 405 GiB free of 480 GiB",
      "statusLine": "canonical media namespace is /data/downloads and /data/media/..."
    },
    {
      "title": "Schedules",
      "stateClass": "busy",
      "stateText": "queued",
      "value": "Observer summary, Routing drift check, State backup",
      "body": "Visible timers stay on the floor so continuity work is never hidden behind another tool.",
      "statusLine": "next: 24 Apr 08:05"
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
          "value": "sentinel"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-architect-bridge.service",
          "value": "07:00:15 bridge.interrupted_requests_processed"
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
      "auditTrail": [
        {
          "label": "10 Apr 23:14 / runtime logs",
          "value": "ok via local | telegram-architect-bridge.service"
        },
        {
          "label": "10 Apr 23:14 / runtime logs",
          "value": "ok via local | telegram-architect-bridge.service"
        },
        {
          "label": "10 Apr 23:12 / runtime restart",
          "value": "ok via local | telegram-architect-bridge.service"
        }
      ],
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
          "value": "07:00:15 bridge.interrupted_requests_processed"
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
          "value": "07:00:15 bridge.interrupted_requests_processed"
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
          "value": "19:15:45 Started whatsapp-govorun-bridge.service - WhatsApp Govorun Bridge (Codex)."
        },
        {
          "label": "govorun-whatsapp-bridge.service",
          "value": "07:00:15 bridge.started"
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
      "stateClass": "danger",
      "stateText": "degraded",
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
          "value": "deactivating / activating"
        }
      ],
      "recentJobs": [
        {
          "label": "signal-oracle-bridge.service",
          "value": "07:00:15 2026-04-24 07:00:15,792 WARNING Signal event stream failed: <urlopen error [Errno 111] Connection refused>"
        },
        {
          "label": "oracle-signal-bridge.service",
          "value": "07:00:14 Starting oracle-signal-bridge.service - Oracle Signal Bridge..."
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "expected active, got deactivating"
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
          "value": "07:00:15 bridge.interrupted_requests_processed"
        },
        {
          "label": "mavali-eth-receipt-monitor.timer",
          "value": "19:15:42 Started mavali-eth-receipt-monitor.timer - Poll for confirmed inbound ETH for mavali_eth."
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
          "label": "07:45:46 snapshot",
          "value": "169 elements | snap-1c09f1fc"
        },
        {
          "label": "07:45:42 tabs.open",
          "value": "x.com/search"
        },
        {
          "label": "07:45:33 snapshot",
          "value": "146 elements | snap-4f59332a"
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
            "value": "existing_session / stopped"
          },
          {
            "label": "auth posture",
            "value": "no explicit auth cue"
          },
          {
            "label": "manual takeover",
            "value": "tv helper not visible"
          },
          {
            "label": "tab footprint",
            "value": "0 live tabs / no http tabs"
          }
        ],
        "targets": [
          {
            "label": "current target",
            "value": "no live browser target"
          }
        ],
        "captures": [
          {
            "label": "captures",
            "value": "no retained captures"
          }
        ],
        "activity": [
          {
            "label": "07:45:46 snapshot",
            "value": "169 elements | snap-1c09f1fc"
          },
          {
            "label": "07:45:42 tabs.open",
            "value": "x.com/search"
          },
          {
            "label": "07:45:33 snapshot",
            "value": "146 elements | snap-4f59332a"
          },
          {
            "label": "07:45:29 start",
            "value": "browser event"
          }
        ],
        "summary": {
          "current_target": "no live browser target",
          "tab_count": 0,
          "auth_posture": "no explicit auth cue",
          "manual_takeover": "tv helper not visible",
          "capture_dir": "/var/lib/server3-browser-brain/captures",
          "started_at": ""
        }
      }
    }
  ]
};
