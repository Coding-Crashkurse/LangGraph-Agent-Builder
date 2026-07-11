# 12 · orchestrator — multi-agent über A2A, zero API keys

Ein Orchestrator-Flow, der andere **publizierte Agenten** als Bausteine
einbaut. Die Spezialisten sind eigenständige A2A-Agenten — sie könnten genauso
auf einem anderen Server (oder von einem ganz anderen Framework) laufen.

```
orchestrator:   start → LLM Router (greet|shout) ─┬→ A2A Remote Agent (greeter-agent) ─┐
                                                  └→ A2A Remote Agent (shouter-agent) ─┴→ end
specialists:    greeter-agent (fake_llm) · shouter-agent (echo_llm, uppercase)
```

**Shows:** Agenten als Komponenten (`A2A Remote Agent`, mode=node), Routing auf
Spezialisten, echte JSON-RPC-Calls zwischen Flows. Der Router läuft ohne Modell
im Keyword-Modus — mit konfiguriertem Modell entscheidet ein LLM.

```bash
lab run --port 8010 &
cd examples/12_orchestrator
lab flow import greeter_agent.json shouter_agent.json orchestrator.json
# agent_url in orchestrator.json an deinen Port anpassen (Studio: Node-Config)
lab flow publish greeter-agent && lab flow publish shouter-agent && lab flow publish orchestrator

lab flow run orchestrator --input "shout: ship it"
# → SHOUT: SHIP IT
lab flow run orchestrator --input "please greet our guest"
# → Hello there! The greeter agent salutes you.
```

**Varianten:**
- **Agent-as-Tool:** stelle beim `A2A Remote Agent` `mode=tool` und hänge ihn
  per gestrichelter Kante an einen `LLM Agent` — dann entscheidet das LLM per
  Tool-Call, wann der Remote-Agent gerufen wird (braucht ein tool-fähiges Modell).
- **Nested HITL:** enthält ein Spezialist ein `Human Approval`, propagiert das
  `input-required` durch den Orchestrator bis zum ursprünglichen Client
  (Beispiel 06 zeigt das end-to-end).
- **Fremde Agenten:** jede `agent_url` mit A2A-Card funktioniert — auch Agenten,
  die nicht mit lab gebaut wurden.
