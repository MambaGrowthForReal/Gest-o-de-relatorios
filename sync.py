import os
import time
import json
import threading
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Configurações ──────────────────────────────────────────
CLICKUP_TOKEN = os.getenv("CLICKUP_TOKEN")
CLICKUP_WEBHOOK_SECRET = os.getenv("CLICKUP_WEBHOOK_SECRET", "")
SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")
SYNC_TRIGGER_TOKEN = os.getenv("SYNC_TRIGGER_TOKEN", "mamba2026dash")

POLL_INTERVAL_HOURS = 6
NOVOS_CRIATIVOS_LIST_ID = "901700896208"
OFERTAS_LIST_ID = "901703341802"
TIKTOK_FOLDER_ID = "90179850327"
VSL_LEAD_LIST_ID = "901702493697"

CLICKUP_HEADERS  = {"Authorization": CLICKUP_TOKEN}
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

# ── Helpers ClickUp ────────────────────────────────────────

def get_teams():
    r = requests.get("https://api.clickup.com/api/v2/team", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json().get("teams", [])

def get_spaces(team_id):
    r = clickup_get(f"https://api.clickup.com/api/v2/team/{team_id}/space?archived=false")
    return r.json().get("spaces", [])

def get_folders(space_id):
    r = clickup_get(f"https://api.clickup.com/api/v2/space/{space_id}/folder?archived=false")
    return r.json().get("folders", [])

def get_folderless_lists(space_id):
    r = clickup_get(f"https://api.clickup.com/api/v2/space/{space_id}/list?archived=false")
    return r.json().get("lists", [])

def get_lists_in_folder(folder_id):
    r = clickup_get(f"https://api.clickup.com/api/v2/folder/{folder_id}/list?archived=false")
    r.raise_for_status()
    return r.json().get("lists", [])

def clickup_get(url, params=None, max_tentativas=5):
    """Chamada GET à API da ClickUp com espera e nova tentativa automática em caso de 429 (rate limit)."""
    for tentativa in range(max_tentativas):
        r = requests.get(url, headers=CLICKUP_HEADERS, params=params)
        if r.status_code == 429:
            espera = int(r.headers.get("Retry-After", 10))
            print(f"  ⏳ Rate limit (429) — aguardando {espera}s antes de tentar de novo (tentativa {tentativa+1}/{max_tentativas})")
            time.sleep(espera)
            continue
        r.raise_for_status()
        return r
    raise Exception(f"Excedeu {max_tentativas} tentativas por rate limit persistente: {url}")

def get_tasks_in_list(list_id, page=0):
    params = {
        "archived": "false",
        "include_closed": "true",
        "page": page,
        "order_by": "updated",
        "reverse": "true",
    }
    r = clickup_get(f"https://api.clickup.com/api/v2/list/{list_id}/task", params=params)
    data = r.json()
    return data.get("tasks", []), data.get("last_page", True)

def get_task_detail(task_id):
    r = clickup_get(f"https://api.clickup.com/api/v2/task/{task_id}")
    return r.json()

def get_subtasks(task_id):
    r = clickup_get(f"https://api.clickup.com/api/v2/task/{task_id}?include_subtasks=true")
    return r.json().get("subtasks", [])

TIKTOK_STATUS_A_PARTIR_DE_EDICAO = ['em edição', 'aprovação', 'agendamento do post', 'post agendado', 'publicado', 'complete']

def get_existente_por_lista(list_id):
    """Busca no Supabase o historico_assignees já salvo para as tasks de uma lista específica."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/tasks",
        headers=SUPABASE_HEADERS,
        params={"list_id": f"eq.{list_id}", "select": "id,historico_assignees"},
    )
    r.raise_for_status()
    return {row["id"]: row.get("historico_assignees") for row in r.json()}

def merge_historico(historico_json_existente, assignees_json_atual):
    """Mescla quem já foi responsável (histórico) com os responsáveis atuais, sem duplicar."""
    try:
        historico = json.loads(historico_json_existente or "[]")
    except Exception:
        historico = []
    ids_no_historico = {h["id"] for h in historico}
    try:
        atuais = json.loads(assignees_json_atual or "[]")
    except Exception:
        atuais = []
    for a in atuais:
        if a["id"] not in ids_no_historico:
            historico.append(a)
            ids_no_historico.add(a["id"])
    return json.dumps(historico)

def get_tiktok_data_em_edicao_existente():
    """Busca no Supabase o que já está salvo (status + data_em_edicao) para as tasks
    da pasta TikTok, para não perder o timestamp já detectado em syncs anteriores."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/tasks",
        headers=SUPABASE_HEADERS,
        params={"folder_id": f"eq.{TIKTOK_FOLDER_ID}", "select": "id,data_em_edicao,historico_assignees"},
    )
    r.raise_for_status()
    return {row["id"]: row for row in r.json()}

# ── Parser de tarefa ───────────────────────────────────────

def parse_task(task, space_id, space_name, list_id, list_name, folder_id=None, folder_name=None):
    assignees = [{"id": a["id"], "username": a.get("username", ""), "email": a.get("email", "")} for a in task.get("assignees", [])]

    creator_raw = task.get("creator") or {}
    creator = {"id": creator_raw.get("id"), "username": creator_raw.get("username", ""), "email": creator_raw.get("email", "")} if creator_raw else None

    def ts(ms):
        if not ms:
            return None
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()

    return {
        "id":           task["id"],
        "name":         task.get("name", ""),
        "status":       task.get("status", {}).get("status", ""),
        "assignees":    json.dumps(assignees),
        "creator":      json.dumps(creator) if creator else None,
        "space_id":     space_id,
        "space_name":   space_name,
        "list_id":      list_id,
        "list_name":    list_name,
        "folder_id":    folder_id,
        "folder_name":  folder_name,
        "due_date":     ts(task.get("due_date")),
        "start_date":   ts(task.get("start_date")),
        "tags":         json.dumps([t.get("name", "") for t in task.get("tags", [])]),
        "date_created": ts(task.get("date_created")),
        "date_updated": ts(task.get("date_updated")),
        "synced_at":    datetime.now(tz=timezone.utc).isoformat(),
    }

# ── Supabase upsert ────────────────────────────────────────

def upsert_tasks(tasks):
    if not tasks:
        return
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/tasks",
        headers=SUPABASE_HEADERS,
        json=tasks,
    )
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Erro no upsert: {r.status_code} {r.text[:200]}")
    else:
        print(f"  ✅ {len(tasks)} tarefa(s) sincronizada(s)")

# ── Sync especial: Novos criativos com due_date individual ─

def sync_novos_criativos():
    print("  🎯 Sync especial: Novos criativos (due_date individual para todas)")
    page = 0
    total = 0
    recuperados = 0

    try:
        existentes = get_existente_por_lista(NOVOS_CRIATIVOS_LIST_ID)
    except Exception as e:
        print(f"  ⚠️  Erro ao buscar histórico existente (Ads): {e}")
        existentes = {}

    while True:
        tasks_raw, last_page = get_tasks_in_list(NOVOS_CRIATIVOS_LIST_ID, page)
        parsed = []

        for t in tasks_raw:
            p = parse_task(t, "", "Tráfego", NOVOS_CRIATIVOS_LIST_ID, "Novos criativos")

            if p["due_date"] is None:
                try:
                    detail = get_task_detail(t["id"])
                    ms = detail.get("due_date")
                    if ms:
                        p["due_date"] = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
                        recuperados += 1
                        print(f"  📅 {t.get('name', '')[:50]} → {p['due_date'][:10]}")
                    time.sleep(0.3)
                except Exception as e:
                    print(f"  ⚠️  Erro task {t['id']}: {e}")

            p["historico_assignees"] = merge_historico(existentes.get(t["id"]), p["assignees"])

            parsed.append(p)

        if parsed:
            upsert_tasks(parsed)
            total += len(parsed)

        if last_page or not tasks_raw:
            break
        page += 1
        time.sleep(0.5)

    print(f"  ✅ Novos criativos: {total} tasks | {recuperados} due_dates recuperados")

# ── Sync subtasks VSL da lista Ofertas ────────────────────

def sync_vsl_subtasks():
    print("  🎬 Sync VSL: subtasks da lista Ofertas")
    page = 0
    total = 0
    vsl_keywords = ["vsl", "vl's", "vls"]

    try:
        existentes = get_existente_por_lista(OFERTAS_LIST_ID)
    except Exception as e:
        print(f"  ⚠️  Erro ao buscar histórico existente (VSL): {e}")
        existentes = {}

    while True:
        tasks_raw, last_page = get_tasks_in_list(OFERTAS_LIST_ID, page)

        for t in tasks_raw:
            try:
                subtasks = get_subtasks(t["id"])
                time.sleep(0.3)
                for sub in subtasks:
                    name_lower = sub.get("name", "").lower()
                    if not any(kw in name_lower for kw in vsl_keywords):
                        continue
                    detail = get_task_detail(sub["id"])
                    time.sleep(0.3)
                    parsed = parse_task(detail, "", "Prod. Ofertas", OFERTAS_LIST_ID, "Ofertas")
                    parsed["historico_assignees"] = merge_historico(existentes.get(sub["id"]), parsed["assignees"])
                    upsert_tasks([parsed])
                    total += 1
                    print(f"  📹 VSL: {sub.get('name', '')[:50]}")
            except Exception as e:
                print(f"  ⚠️  Erro subtasks task {t['id']}: {e}")

        if last_page or not tasks_raw:
            break
        page += 1
        time.sleep(0.5)

    print(f"  ✅ VSL subtasks: {total} sincronizadas")

# ── Full sync ──────────────────────────────────────────────

def full_sync():
    print(f"\n🔄 Iniciando sync — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    teams = get_teams()
    total = 0

    sync_novos_criativos()
    sync_vsl_subtasks()

    try:
        tiktok_existentes = get_tiktok_data_em_edicao_existente()
    except Exception as e:
        print(f"  ⚠️  Erro ao buscar dados existentes do TikTok: {e}")
        tiktok_existentes = {}

    try:
        vsl_lead_existentes = get_existente_por_lista(VSL_LEAD_LIST_ID)
    except Exception as e:
        print(f"  ⚠️  Erro ao buscar histórico existente (VSL Lead/Microlead): {e}")
        vsl_lead_existentes = {}

    for team in teams:
        spaces = get_spaces(team["id"])
        for space in spaces:
            sid, sname = space["id"], space["name"]
            listas_com_pasta = [(l["id"], l["name"], None, None) for l in get_folderless_lists(sid)]
            for folder in get_folders(sid):
                fid, fname = folder["id"], folder["name"]
                listas_com_pasta += [(l["id"], l["name"], fid, fname) for l in get_lists_in_folder(fid)]

            for lid, lname, fid, fname in listas_com_pasta:
                if lid == NOVOS_CRIATIVOS_LIST_ID:
                    continue  # já sincronizada com recuperação de due_date acima, evita sobrescrever com null
                page = 0
                while True:
                    tasks_raw, last_page = get_tasks_in_list(lid, page)
                    parsed = []
                    for t in tasks_raw:
                        p = parse_task(t, sid, sname, lid, lname, fid, fname)
                        if fid == TIKTOK_FOLDER_ID:
                            existente = tiktok_existentes.get(t["id"], {})
                            ja_tinha = existente.get("data_em_edicao")
                            status_atual = (p["status"] or "").lower().strip()
                            if ja_tinha:
                                p["data_em_edicao"] = ja_tinha
                            elif status_atual in TIKTOK_STATUS_A_PARTIR_DE_EDICAO:
                                p["data_em_edicao"] = p["date_updated"] or p["synced_at"]
                            else:
                                p["data_em_edicao"] = None

                            p["historico_assignees"] = merge_historico(existente.get("historico_assignees"), p["assignees"])
                        elif lid == VSL_LEAD_LIST_ID:
                            p["historico_assignees"] = merge_historico(vsl_lead_existentes.get(t["id"]), p["assignees"])
                        parsed.append(p)
                    upsert_tasks(parsed)
                    total += len(parsed)
                    if last_page or not tasks_raw:
                        break
                    page += 1
                    time.sleep(0.5)

    print(f"✅ Sync completo — {total} tarefas processadas\n")

def adicionar_ao_historico(task_id, assignee):
    """Atualiza o historico_assignees de UMA task específica, sem esperar o próximo sync."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/tasks",
        headers=SUPABASE_HEADERS,
        params={"id": f"eq.{task_id}", "select": "historico_assignees"},
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        print(f"  ℹ️  Webhook: task {task_id} ainda não está no Supabase, ignorando (próximo sync completo resolve)")
        return

    try:
        historico = json.loads(rows[0].get("historico_assignees") or "[]")
    except Exception:
        historico = []

    if not any(h.get("id") == assignee.get("id") for h in historico):
        historico.append(assignee)
        r2 = requests.patch(
            f"{SUPABASE_URL}/rest/v1/tasks",
            headers=SUPABASE_HEADERS,
            params={"id": f"eq.{task_id}"},
            json={"historico_assignees": json.dumps(historico)},
        )
        r2.raise_for_status()
        print(f"  🔔 Webhook: {assignee.get('username','?')} adicionado ao histórico da task {task_id}")

# ── Servidor HTTP para disparo manual do sync ──────────────

sync_em_andamento = False
sync_lock = threading.Lock()

def rodar_full_sync_protegido():
    global sync_em_andamento
    with sync_lock:
        if sync_em_andamento:
            return False
        sync_em_andamento = True
    try:
        full_sync()
    except Exception as e:
        print(f"❌ Erro no sync: {e}")
    finally:
        sync_em_andamento = False
    return True

class SyncTriggerHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "x-sync-token")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/sync"):
            token = self.headers.get("x-sync-token", "")
            if token != SYNC_TRIGGER_TOKEN:
                self.send_response(401)
                self._cors()
                self.end_headers()
                self.wfile.write(b"unauthorized")
                return
            if sync_em_andamento:
                self.send_response(409)
                self._cors()
                self.end_headers()
                self.wfile.write(b"sync ja em andamento")
                return
            threading.Thread(target=rodar_full_sync_protegido, daemon=True).start()
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b"sync iniciado")
        elif self.path.startswith("/status"):
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b"em_andamento" if sync_em_andamento else b"ocioso")
        elif self.path.startswith("/webhook/registrar"):
            token = self.headers.get("x-sync-token", "")
            if token != SYNC_TRIGGER_TOKEN:
                self.send_response(401)
                self._cors()
                self.end_headers()
                self.wfile.write(b"unauthorized")
                return
            try:
                host = self.headers.get("Host", "")
                endpoint = f"https://{host}/webhook/clickup"
                teams = get_teams()
                team_id = teams[0]["id"]
                r = requests.post(
                    f"https://api.clickup.com/api/v2/team/{team_id}/webhook",
                    headers=CLICKUP_HEADERS,
                    json={"endpoint": endpoint, "events": ["taskAssigneeUpdated"]},
                )
                resposta_json = r.json()
                secret = resposta_json.get("webhook", {}).get("secret", "")
                mensagem = (
                    f"Status: {r.status_code}\n"
                    f"Resposta: {r.text}\n\n"
                    f"⚠️ IMPORTANTE: copia esse secret e cola como variável de ambiente\n"
                    f"CLICKUP_WEBHOOK_SECRET no Railway:\n{secret}\n"
                )
                self.send_response(200)
                self._cors()
                self.end_headers()
                self.wfile.write(mensagem.encode())
            except Exception as e:
                self.send_response(500)
                self._cors()
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/webhook/clickup"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            # Valida a assinatura: garante que a requisição veio mesmo da ClickUp
            assinatura_recebida = self.headers.get("X-Signature", "")
            if not CLICKUP_WEBHOOK_SECRET:
                print("  ⚠️  CLICKUP_WEBHOOK_SECRET não configurado — rejeitando webhook por segurança")
                self.send_response(401)
                self._cors()
                self.end_headers()
                self.wfile.write(b"webhook secret nao configurado")
                return

            assinatura_esperada = hmac.new(
                CLICKUP_WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(assinatura_recebida, assinatura_esperada):
                print("  🚫 Webhook com assinatura inválida — requisição rejeitada")
                self.send_response(401)
                self._cors()
                self.end_headers()
                self.wfile.write(b"assinatura invalida")
                return

            try:
                data = json.loads(body or b"{}")
                task_id = data.get("task_id")
                for item in data.get("history_items", []):
                    if item.get("field") == "assignee_add" and task_id:
                        depois = item.get("after") or {}
                        if depois.get("id"):
                            adicionar_ao_historico(task_id, {
                                "id": depois.get("id"),
                                "username": depois.get("username", ""),
                                "email": depois.get("email", ""),
                            })
            except Exception as e:
                print(f"  ⚠️  Erro processando webhook: {e}")
            # Responde rápido pro ClickUp, sempre 200 (mesmo se algo falhar internamente)
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silencia logs de HTTP no console do Railway

def iniciar_servidor_http():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SyncTriggerHandler)
    print(f"🌐 Servidor de trigger ouvindo na porta {port}")
    server.serve_forever()

# ── Loop principal ─────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 ClickUp Sync iniciado")
    threading.Thread(target=iniciar_servidor_http, daemon=True).start()
    while True:
        rodar_full_sync_protegido()
        print(f"⏳ Próximo sync em {POLL_INTERVAL_HOURS}h...")
        time.sleep(POLL_INTERVAL_HOURS * 3600)
