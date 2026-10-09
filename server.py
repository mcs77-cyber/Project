import os
import json
import uuid
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse
import http.server
import socketserver
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Carrega variáveis de ambiente (.env) se existirem
load_dotenv()

# ==============================================================================
# 1. SERIALIZADOR JSON E CONEXÃO COM BANCO DE DADOS (NEON)
# ==============================================================================

class CustomJSONEncoder(json.JSONEncoder):
    """Converte tipos do PostgreSQL (UUID, datetime, Decimal) para JSON válido."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

class UserRole:
    PUBLICO = "PUBLICO"
    EMPRESA = "EMPRESA"
    ADMIN = "ADMIN"

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_db_connection():
    """Retorna uma conexão com o PostgreSQL Neon ou None se a URL não estiver configurada."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return psycopg2.connect(url, cursor_factory=RealDictCursor)

def init_db():
    """Cria a estrutura de tabelas no Neon e garante a presença dos dados de teste."""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            print("⚠️ DATABASE_URL não configurada. Pulei a inicialização do banco.")
            return

        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    pass_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id UUID PRIMARY KEY,
                    company_id UUID REFERENCES users(id),
                    company_name VARCHAR(255),
                    title VARCHAR(255) NOT NULL,
                    category VARCHAR(100),
                    price NUMERIC(10, 2) NOT NULL,
                    stock INT NOT NULL,
                    likes_count INT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id UUID PRIMARY KEY,
                    user_id UUID REFERENCES users(id),
                    event_id UUID REFERENCES events(id),
                    event_title VARCHAR(255),
                    qr_hash VARCHAR(255) UNIQUE NOT NULL,
                    is_used BOOLEAN DEFAULT FALSE,
                    validated_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS company_requests (
                    id VARCHAR(50) PRIMARY KEY,
                    user_id UUID REFERENCES users(id),
                    company_name VARCHAR(255),
                    cnpj VARCHAR(50),
                    email VARCHAR(255),
                    description TEXT,
                    status VARCHAR(50) DEFAULT 'PENDENTE',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS financial_transactions (
                    id UUID PRIMARY KEY,
                    ticket_id UUID REFERENCES tickets(id),
                    total_amount NUMERIC(10, 2),
                    platform_share_20 NUMERIC(10, 2),
                    company_share_80 NUMERIC(10, 2),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token VARCHAR(255) PRIMARY KEY,
                    user_id UUID REFERENCES users(id),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            conn.commit()

            # Garante que os 3 usuários de teste existam no banco
            admin_id = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
            company_id = "b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22"
            public_id = "c2eebc99-9c0b-4ef8-bb6d-6bb9bd380a33"
            default_event_id = "e3a8910d-2b4a-4f51-b883-92f701b918a2"

            pass_admin = hash_password("admin123")
            pass_empresa = hash_password("empresa123")
            pass_publico = hash_password("user123")

            cur.execute("""
                INSERT INTO users (id, name, email, pass_hash, role) VALUES
                (%s, 'Leonardo Medeiros', 'admin@alltickets.com', %s, 'ADMIN'),
                (%s, 'Mariana Produções', 'empresa@mariana.com', %s, 'EMPRESA'),
                (%s, 'Isadora Fernandes', 'isadora@email.com', %s, 'PUBLICO')
                ON CONFLICT (email) DO NOTHING;
            """, (admin_id, pass_admin, company_id, pass_empresa, public_id, pass_publico))

            cur.execute("""
                INSERT INTO events (id, company_id, company_name, title, category, price, stock, likes_count) VALUES
                (%s, %s, 'Mariana Produções', 'Maceió Summer Sounds 2026', 'Shows e Festivais', 100.00, 10, 18)
                ON CONFLICT (id) DO NOTHING;
            """, (default_event_id, company_id))

            cur.execute("""
                INSERT INTO company_requests (id, user_id, company_name, cnpj, email, description, status) VALUES
                ('REQ-101', %s, 'Isadora Eventos Culturais', '12.345.678/0001-90', 'isadora@email.com', 'Produção de Peças Teatrais e Festivais', 'PENDENTE')
                ON CONFLICT (id) DO NOTHING;
            """, (public_id,))

            conn.commit()

    except Exception as e:
        print(f"⚠️ Aviso na inicialização do Neon: {e}")
    finally:
        if conn:
            conn.close()

# Tenta inicializar as tabelas
try:
    init_db()
except Exception as e:
    print(f"Aviso de inicialização ignorado: {e}")

# ==============================================================================
# 2. FRONTEND HTML5 + JS ES6 (DESIGN DARK ESTON TEMPLATE INSPIRATION)
# ==============================================================================

HTML_PAGE = """<!DOCTYPE html>
<html lang="pt-BR" data-bs-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>All Tickets. — Movie Studio & Event Platform</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #0d0d0f;
      --card-bg: #16161a;
      --card-border: #24242c;
      --accent-red: #ff2a4b;
      --accent-red-hover: #d91d3a;
      --text-muted: #8e8e9e;
    }
    body {
      background-color: var(--bg-dark);
      color: #f1f1f5;
      font-family: 'Plus Jakarta Sans', sans-serif;
      padding-bottom: 60px;
    }
    .navbar {
      background-color: rgba(13, 13, 15, 0.9) !important;
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--card-border);
    }
    .brand-logo {
      font-weight: 800;
      font-size: 1.6rem;
      letter-spacing: -0.5px;
      color: #ffffff;
    }
    .brand-dot {
      color: var(--accent-red);
    }
    .hero-banner {
      background: linear-gradient(180deg, rgba(22, 22, 26, 0.4) 0%, rgba(13, 13, 15, 1) 100%),
                  radial-gradient(circle at top right, rgba(255, 42, 75, 0.15), transparent 40%);
      border-radius: 20px;
      padding: 50px 40px;
      margin-bottom: 40px;
      border: 1px solid var(--card-border);
    }
    .hero-title {
      font-size: 2.8rem;
      font-weight: 800;
      letter-spacing: -1px;
      line-height: 1.1;
    }
    .btn-eston {
      background-color: var(--accent-red);
      color: #ffffff;
      font-weight: 700;
      border: none;
      padding: 10px 24px;
      border-radius: 8px;
      transition: all 0.2s ease;
    }
    .btn-eston:hover {
      background-color: var(--accent-red-hover);
      color: #ffffff;
      transform: translateY(-2px);
    }
    .card-eston {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      overflow: hidden;
      transition: all 0.25s cubic-bezier(0.165, 0.84, 0.44, 1);
    }
    .card-eston:hover {
      transform: translateY(-6px);
      border-color: rgba(255, 42, 75, 0.4);
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
    }
    .nav-pills .nav-link {
      color: var(--text-muted);
      font-weight: 600;
      border-radius: 8px;
      padding: 8px 18px;
    }
    .nav-pills .nav-link.active {
      background-color: var(--accent-red);
      color: #ffffff;
    }
    .badge-category {
      background-color: rgba(255, 42, 75, 0.12);
      color: var(--accent-red);
      border: 1px solid rgba(255, 42, 75, 0.3);
      font-weight: 700;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .qr-badge {
      font-family: monospace;
      font-size: 1rem;
      background: #0d0d0f;
      color: #00ff88;
      border: 1px dashed #00ff88;
      padding: 6px 12px;
      border-radius: 6px;
    }
    .modal-content {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
    }
  </style>
</head>
<body>

  <!-- NAVBAR ESTON STYLE -->
  <nav class="navbar navbar-expand-lg navbar-dark sticky-top">
    <div class="container">
      <a class="navbar-brand brand-logo" href="#">All Tickets<span class="brand-dot">.</span></a>
      <div class="d-flex align-items-center gap-3 ms-auto" id="authNavArea"></div>
    </div>
  </nav>

  <div class="container my-4">

    <!-- HERO BANNER -->
    <div class="hero-banner">
      <div class="row align-items-center">
        <div class="col-lg-8">
          <span class="badge badge-category mb-3">Live Experiences & Digital Distribution</span>
          <h1 class="hero-title mb-3">Makes & Distributes <br><span style="color: var(--accent-red);">Ticket Experiences.</span></h1>
          <p class="text-secondary lead fs-6 mb-0">Plataforma centralizada para venda de ingressos, emissão de voucher criptográfico e validação na portaria em tempo real.</p>
        </div>
      </div>
    </div>

    <!-- NAVEGAÇÃO DE ABAS PROTEGIDA POR RBAC -->
    <ul class="nav nav-pills mb-4 gap-2" id="mainTabs">
      <li class="nav-item">
        <button class="nav-link active" onclick="switchTab('public')">🎉 Feed de Eventos</button>
      </li>
      <li class="nav-item d-none" id="tabProducer">
        <button class="nav-link" onclick="switchTab('company')">📊 Painel do Produtor</button>
      </li>
      <li class="nav-item d-none" id="tabAdmin">
        <button class="nav-link" onclick="switchTab('admin')">⚙️ Painel Admin Global</button>
      </li>
    </ul>

    <!-- VISÃO 1: FEED PÚBLICO -->
    <div id="view-public" class="tab-content">
      <div class="d-flex justify-content-between align-items-center mb-4">
        <h3 class="fw-bold m-0">Próximos Eventos</h3>
      </div>

      <div class="row g-4" id="eventsGrid"></div>

      <!-- CARTEIRA DIGITAL -->
      <div class="mt-5 d-none" id="walletSection">
        <h4 class="fw-bold mb-3">💼 Minha Carteira Digital de Ingressos</h4>
        <div class="list-group" id="userWallet"></div>
      </div>
    </div>

    <!-- VISÃO 2: PAINEL DO PRODUTOR (EMPRESA) -->
    <div id="view-company" class="tab-content d-none">
      <h3 class="fw-bold mb-4">Painel do Produtor de Eventos</h3>
      <div class="row g-4">
        <div class="col-lg-6">
          <div class="card card-eston p-4">
            <h5 class="fw-bold mb-3 text-white">➕ Publicar Novo Evento</h5>
            <form onsubmit="handleCreateEvent(event)">
              <div class="mb-3">
                <label class="form-label text-secondary small fw-semibold">Título do Evento</label>
                <input type="text" id="evTitle" class="form-control bg-dark text-white border-secondary" required placeholder="Ex: Festival Rock Maceió">
              </div>
              <div class="mb-3">
                <label class="form-label text-secondary small fw-semibold">Categoria</label>
                <select id="evCategory" class="form-select bg-dark text-white border-secondary">
                  <option value="Shows e Festivais">Shows e Festivais</option>
                  <option value="Teatro e Cultura">Teatro e Cultura</option>
                  <option value="Festas e Nightlife">Festas e Nightlife</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label text-secondary small fw-semibold">Preço por Ingresso (R$)</label>
                <input type="number" id="evPrice" class="form-control bg-dark text-white border-secondary" step="0.01" required placeholder="100.00">
              </div>
              <div class="mb-4">
                <label class="form-label text-secondary small fw-semibold">Estoque Inicial</label>
                <input type="number" id="evStock" class="form-control bg-dark text-white border-secondary" required placeholder="50">
              </div>
              <button type="submit" class="btn btn-eston w-100">Publicar Evento</button>
            </form>
          </div>
        </div>

        <div class="col-lg-6">
          <div class="card card-eston p-4">
            <h5 class="fw-bold mb-3 text-white">🔍 Validador de Portaria (Antifraude)</h5>
            <p class="text-secondary small">Insira o código Hash único impresso no bilhete para autorizar a entrada e queimar o ingresso.</p>
            <div class="input-group mb-3">
              <input type="text" id="qrInput" class="form-control bg-dark text-white border-secondary" placeholder="Ex: QR-A9F82B10C4">
              <button class="btn btn-success fw-bold" onclick="handleValidateTicket()">Validar Entrada</button>
            </div>
            <div id="validationResult"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- VISÃO 3: PAINEL ADMINISTRATIVO GLOBAL -->
    <div id="view-admin" class="tab-content d-none">
      <h3 class="fw-bold mb-4">Painel do Administrador All Tickets</h3>
      
      <div class="row g-4 mb-4">
        <div class="col-md-6">
          <div class="card card-eston p-4 text-center">
            <span class="text-secondary small fw-bold">VOLUME TOTAL TRANSACIONADO</span>
            <h2 class="fw-800 text-white mt-2" id="adminTotalVolume">R$ 0,00</h2>
          </div>
        </div>
        <div class="col-md-6">
          <div class="card card-eston p-4 text-center">
            <span class="text-secondary small fw-bold">COMISSÃO DA PLATAFORMA (20%)</span>
            <h2 class="fw-800 mt-2" style="color: var(--accent-red);" id="adminPlatformShare">R$ 0,00</h2>
          </div>
        </div>
      </div>

      <div class="card card-eston p-4 mb-4">
        <h5 class="fw-bold mb-3 text-white">📋 Solicitações de Parceria Empresarial Pendentes</h5>
        <div id="adminRequestsList"></div>
      </div>

      <div class="card card-eston p-4">
        <h5 class="fw-bold mb-3 text-white">👥 Gestão de Usuários e Promoção de Papéis</h5>
        <div id="adminUsersList"></div>
      </div>
    </div>

  </div>

  <!-- MODAL DE LOGIN -->
  <div class="modal fade" id="loginModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content p-3">
        <div class="modal-header border-0">
          <h4 class="modal-title fw-bold text-white">Entrar na Conta<span class="brand-dot">.</span></h4>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          <form onsubmit="handleLogin(event)">
            <div class="mb-3">
              <label class="form-label text-secondary small">E-mail de Acesso</label>
              <input type="email" id="loginEmail" class="form-control bg-dark text-white border-secondary" required>
            </div>
            <div class="mb-4">
              <label class="form-label text-secondary small">Senha</label>
              <input type="password" id="loginPassword" class="form-control bg-dark text-white border-secondary" required>
            </div>
            <button type="submit" class="btn btn-eston w-100 mb-3">Autenticar no Sistema</button>
          </form>

          <p class="text-center text-secondary small mb-3">
            Não tem uma conta? <a href="#" class="text-white fw-bold text-decoration-none" onclick="closeModal('loginModal'); openModal('registerModal');">Criar Conta</a>
          </p>

          <hr class="border-secondary my-4">
          <p class="text-secondary small fw-bold text-center mb-3">ACESSO RÁPIDO PARA TESTES DOS 3 PERFIS:</p>
          <div class="d-grid gap-2">
            <button class="btn btn-outline-warning btn-sm" onclick="quickLogin('admin@alltickets.com', 'admin123')">👑 Logar como Admin</button>
            <button class="btn btn-outline-info btn-sm" onclick="quickLogin('empresa@mariana.com', 'empresa123')">🏢 Logar como Empresa</button>
            <button class="btn btn-outline-light btn-sm" onclick="quickLogin('isadora@email.com', 'user123')">👤 Logar como Público</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- MODAL DE REGISTRO -->
  <div class="modal fade" id="registerModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content p-3">
        <div class="modal-header border-0">
          <h4 class="modal-title fw-bold text-white">Criar Nova Conta<span class="brand-dot">.</span></h4>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          <form onsubmit="handleRegister(event)">
            <div class="mb-3">
              <label class="form-label text-secondary small">Nome Completo</label>
              <input type="text" id="regName" class="form-control bg-dark text-white border-secondary" required>
            </div>
            <div class="mb-3">
              <label class="form-label text-secondary small">E-mail</label>
              <input type="email" id="regEmail" class="form-control bg-dark text-white border-secondary" required>
            </div>
            <div class="mb-4">
              <label class="form-label text-secondary small">Senha</label>
              <input type="password" id="regPassword" class="form-control bg-dark text-white border-secondary" required>
            </div>
            <button type="submit" class="btn btn-eston w-100">Finalizar Cadastro</button>
          </form>
          <p class="text-center text-secondary small mt-3 mb-0">
            Já tem uma conta? <a href="#" class="text-white fw-bold text-decoration-none" onclick="closeModal('registerModal'); openModal('loginModal');">Entrar aqui</a>
          </p>
        </div>
      </div>
    </div>
  </div>

  <!-- MODAL PARCERIA EMPRESARIAL -->
  <div class="modal fade" id="requestModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content p-3">
        <div class="modal-header border-0">
          <h4 class="modal-title fw-bold text-white">Solicitar Parceria Empresarial</h4>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          <p class="text-secondary small mb-3">Após enviar, a proposta passará por análise do Administrador. Uma vez aprovada, sua conta será promovida para Produtor de Eventos.</p>
          <form onsubmit="handleSendRequest(event)">
            <div class="mb-3">
              <label class="form-label text-secondary small">Razão Social / Nome Fantasia</label>
              <input type="text" id="reqName" class="form-control bg-dark text-white border-secondary" required>
            </div>
            <div class="mb-3">
              <label class="form-label text-secondary small">CNPJ</label>
              <input type="text" id="reqCnpj" class="form-control bg-dark text-white border-secondary" placeholder="00.000.000/0001-00" required>
            </div>
            <div class="mb-4">
              <label class="form-label text-secondary small">Descrição da Empresa & Proposta</label>
              <textarea id="reqDesc" class="form-control bg-dark text-white border-secondary" rows="3" required></textarea>
            </div>
            <button type="submit" class="btn btn-eston w-100">Enviar Solicitação</button>
          </form>
        </div>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    let sessionToken = localStorage.getItem('token') || null;
    let currentUser = null;

    async function init() {
      if (sessionToken) {
        await fetchCurrentUser();
      } else {
        renderAuthUI();
      }
      loadEvents();
    }

    async function fetchCurrentUser() {
      try {
        const res = await fetch('/api/v1/auth/me', {
          headers: { 'Authorization': `Bearer ${sessionToken}` }
        });
        if (res.ok) {
          currentUser = await res.json();
          renderAuthUI();
          loadWallet();
          if (currentUser.role === 'ADMIN') loadAdminData();
        } else {
          logout();
        }
      } catch (err) {
        logout();
      }
    }

    function renderAuthUI() {
      const authArea = document.getElementById('authNavArea');
      const tabProducer = document.getElementById('tabProducer');
      const tabAdmin = document.getElementById('tabAdmin');
      const walletSec = document.getElementById('walletSection');

      if (currentUser) {
        let badgeColor = currentUser.role === 'ADMIN' ? 'bg-warning text-dark' : currentUser.role === 'EMPRESA' ? 'bg-info text-dark' : 'bg-secondary';
        let partnerOption = currentUser.role === 'PUBLICO' 
          ? `<button class="btn btn-outline-light btn-sm rounded-2 me-2" onclick="checkPartnerStatus()">🤝 Seja um Produtor</button>` 
          : '';

        authArea.innerHTML = `
          ${partnerOption}
          <span class="small fw-bold text-white me-2">${currentUser.name} <span class="badge ${badgeColor}">${currentUser.role}</span></span>
          <button class="btn btn-outline-danger btn-sm rounded-2" onclick="logout()">Sair</button>
        `;

        walletSec.classList.remove('d-none');

        if (currentUser.role === 'EMPRESA') {
          tabProducer.classList.remove('d-none');
          tabAdmin.classList.add('d-none');
        } else if (currentUser.role === 'ADMIN') {
          tabProducer.classList.remove('d-none');
          tabAdmin.classList.remove('d-none');
        } else {
          tabProducer.classList.add('d-none');
          tabAdmin.classList.add('d-none');
        }
      } else {
        authArea.innerHTML = `
          <button class="btn btn-outline-light btn-sm rounded-2" onclick="openModal('loginModal')">Entrar</button>
          <button class="btn btn-eston btn-sm" onclick="openModal('registerModal')">Criar Conta</button>
        `;
        tabProducer.classList.add('d-none');
        tabAdmin.classList.add('d-none');
        walletSec.classList.add('d-none');
      }
    }

    async function handleLogin(e) {
      e.preventDefault();
      const email = document.getElementById('loginEmail').value;
      const pass = document.getElementById('loginPassword').value;

      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pass })
      });

      const data = await res.json();
      if (!res.ok) {
        alert(`Erro: ${data.error}`);
        return;
      }

      sessionToken = data.token;
      localStorage.setItem('token', sessionToken);
      currentUser = data.user;

      closeModal('loginModal');
      renderAuthUI();
      loadWallet();
      if (currentUser.role === 'ADMIN') loadAdminData();
      alert(`👋 Bem-vindo(a), ${currentUser.name}!`);
    }

    async function handleRegister(e) {
      e.preventDefault();
      const name = document.getElementById('regName').value;
      const email = document.getElementById('regEmail').value;
      const pass = document.getElementById('regPassword').value;

      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password: pass })
      });

      const data = await res.json();
      if (!res.ok) {
        alert(`Erro: ${data.error}`);
        return;
      }

      sessionToken = data.token;
      localStorage.setItem('token', sessionToken);
      currentUser = data.user;

      closeModal('registerModal');
      renderAuthUI();
      alert(`🎉 Conta criada com sucesso! Bem-vindo(a), ${currentUser.name}.`);
    }

    function quickLogin(email, pass) {
      document.getElementById('loginEmail').value = email;
      document.getElementById('loginPassword').value = pass;
      handleLogin(new Event('submit'));
    }

    function logout() {
      sessionToken = null;
      currentUser = null;
      localStorage.removeItem('token');
      renderAuthUI();
      switchTab('public');
    }

    function switchTab(tab) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.add('d-none'));
      document.querySelectorAll('#mainTabs .nav-link').forEach(el => el.classList.remove('active'));
      document.getElementById(`view-${tab}`).classList.remove('d-none');
      if (event && event.target) event.target.classList.add('active');
    }

    async function loadEvents() {
      const res = await fetch('/api/v1/events');
      if (!res.ok) return;
      const events = await res.json();
      const grid = document.getElementById('eventsGrid');

      grid.innerHTML = events.map(ev => `
        <div class="col-md-4">
          <div class="card card-eston h-100">
            <div class="card-body p-4 d-flex flex-column">
              <div>
                <span class="badge badge-category mb-2">${ev.category}</span>
                <h5 class="fw-bold text-white mb-1">${ev.title}</h5>
                <p class="text-secondary small mb-3">Por: ${ev.company_name}</p>
              </div>
              <div class="mt-auto">
                <div class="d-flex justify-content-between align-items-baseline mb-3">
                  <span class="fs-4 fw-bold text-white">R$ ${Number(ev.price).toFixed(2)}</span>
                  <span class="small text-secondary">Estoque: <strong>${ev.stock}</strong></span>
                </div>
                <button class="btn btn-eston w-100" onclick="buyTicket('${ev.id}')" ${ev.stock <= 0 ? 'disabled' : ''}>
                  ${ev.stock > 0 ? 'Comprar Ingresso' : 'Esgotado'}
                </button>
              </div>
            </div>
          </div>
        </div>
      `).join('');
    }

    async function buyTicket(eventId) {
      if (!currentUser) {
        alert('🔒 Faça login para realizar a compra!');
        openModal('loginModal');
        return;
      }

      const res = await fetch(`/api/v1/events/${eventId}/purchase`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_method: 'PIX' })
      });

      const data = await res.json();
      if (!res.ok) {
        alert(`Erro (${res.status}): ${data.error}`);
        return;
      }

      alert(`🎉 Compra Concluída com Sucesso!\n\n` +
            `Evento: ${data.ticket.event_title}\n` +
            `Seu ingresso foi emitido e salvo na sua Carteira Digital.\n` +
            `Código Hash Criptográfico: ${data.ticket.qr_hash}`);

      loadEvents();
      loadWallet();
      if (currentUser.role === 'ADMIN') loadAdminData();
    }

    async function loadWallet() {
      if (!currentUser) return;
      const res = await fetch('/api/v1/tickets', {
        headers: { 'Authorization': `Bearer ${sessionToken}` }
      });
      if (!res.ok) return;
      const tickets = await res.json();
      const wallet = document.getElementById('userWallet');

      if (tickets.length === 0) {
        wallet.innerHTML = '<div class="list-group-item bg-dark text-secondary border-secondary">Nenhum ingresso comprado ainda.</div>';
        return;
      }

      wallet.innerHTML = tickets.map(t => `
        <div class="list-group-item bg-dark border-secondary text-white d-flex justify-content-between align-items-center p-3">
          <div>
            <h6 class="fw-bold mb-1">${t.event_title}</h6>
            <small class="text-secondary">Emitido em: ${new Date(t.created_at).toLocaleString()}</small>
          </div>
          <div>
            <span class="qr-badge">${t.qr_hash}</span>
            <span class="badge ${t.is_used ? 'bg-danger' : 'bg-success'} ms-2">
              ${t.is_used ? 'UTILIZADO' : 'VÁLIDO'}
            </span>
          </div>
        </div>
      `).join('');
    }

    async function handleCreateEvent(e) {
      e.preventDefault();
      const payload = {
        title: document.getElementById('evTitle').value,
        category: document.getElementById('evCategory').value,
        price: parseFloat(document.getElementById('evPrice').value),
        stock: parseInt(document.getElementById('evStock').value)
      };

      const res = await fetch('/api/v1/events', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok) {
        alert(`Erro (${res.status}): ${data.error}`);
        return;
      }

      alert('✅ Evento cadastrado com sucesso!');
      loadEvents();
    }

    async function handleValidateTicket() {
      const hash = document.getElementById('qrInput').value.trim();
      const resultDiv = document.getElementById('validationResult');

      const res = await fetch('/api/v1/tickets/validate', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ qr_hash: hash })
      });

      const data = await res.json();
      if (!res.ok) {
        resultDiv.innerHTML = `<div class="alert alert-danger mb-0">${data.error}</div>`;
      } else {
        resultDiv.innerHTML = `<div class="alert alert-success mb-0">✅ ${data.message}<br><small>Evento: ${data.event_title}</small></div>`;
        loadWallet();
      }
    }

    async function checkPartnerStatus() {
      const res = await fetch('/api/v1/company-requests/my-status', {
        headers: { 'Authorization': `Bearer ${sessionToken}` }
      });
      const data = await res.json();

      if (data.status === 'PENDENTE') {
        alert(`⌛ Sua solicitação de parceria para "${data.request.company_name}" está em análise pelo Administrador.`);
      } else if (data.status === 'REJEITADO') {
        alert('❌ Sua solicitação anterior foi rejeitada. Você pode enviar uma nova proposta.');
        openModal('requestModal');
      } else {
        openModal('requestModal');
      }
    }

    async function handleSendRequest(e) {
      e.preventDefault();
      const payload = {
        company_name: document.getElementById('reqName').value,
        cnpj: document.getElementById('reqCnpj').value,
        description: document.getElementById('reqDesc').value
      };

      const res = await fetch('/api/v1/company-requests', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (res.ok) {
        alert('✅ Solicitação enviada com sucesso!');
        closeModal('requestModal');
      } else {
        alert(`Erro: ${data.error}`);
      }
    }

    async function loadAdminData() {
      const resFin = await fetch('/api/v1/admin/stats', {
        headers: { 'Authorization': `Bearer ${sessionToken}` }
      });
      if (resFin.ok) {
        const fin = await resFin.json();
        document.getElementById('adminTotalVolume').innerText = `R$ ${Number(fin.total_volume).toFixed(2)}`;
        document.getElementById('adminPlatformShare').innerText = `R$ ${Number(fin.platform_share).toFixed(2)}`;
      }

      const resReq = await fetch('/api/v1/company-requests', {
        headers: { 'Authorization': `Bearer ${sessionToken}` }
      });
      if (resReq.ok) {
        const reqs = await resReq.json();
        const list = document.getElementById('adminRequestsList');
        if (reqs.length === 0) {
          list.innerHTML = '<p class="text-secondary small m-0">Nenhuma solicitação pendente.</p>';
        } else {
          list.innerHTML = reqs.map(r => `
            <div class="d-flex justify-content-between align-items-center border-bottom border-secondary py-3">
              <div>
                <strong class="text-white">${r.company_name}</strong> (CNPJ: ${r.cnpj})<br>
                <small class="text-secondary">${r.description} | Status: <span class="badge bg-warning text-dark">${r.status}</span></small>
              </div>
              <div>
                ${r.status === 'PENDENTE' ? `
                  <button class="btn btn-sm btn-success fw-bold" onclick="approveRequest('${r.id}', 'APROVADO')">Aprovar & Promover</button>
                  <button class="btn btn-sm btn-outline-danger" onclick="approveRequest('${r.id}', 'REJEITADO')">Rejeitar</button>
                ` : `<span class="badge bg-secondary">${r.status}</span>`}
              </div>
            </div>
          `).join('');
        }
      }

      const resUsers = await fetch('/api/v1/admin/users', {
        headers: { 'Authorization': `Bearer ${sessionToken}` }
      });
      if (resUsers.ok) {
        const users = await resUsers.json();
        const list = document.getElementById('adminUsersList');
        list.innerHTML = users.map(u => `
          <div class="d-flex justify-content-between align-items-center border-bottom border-secondary py-2">
            <div>
              <strong class="text-white">${u.name}</strong> (${u.email})<br>
              <small class="text-secondary">Papel Atual: <span class="badge bg-secondary">${u.role}</span></small>
            </div>
            <div>
              <select class="form-select form-select-sm bg-dark text-white border-secondary d-inline-block w-auto" onchange="promoteUser('${u.id}', this.value)">
                <option value="PUBLICO" ${u.role === 'PUBLICO' ? 'selected' : ''}>PÚBLICO</option>
                <option value="EMPRESA" ${u.role === 'EMPRESA' ? 'selected' : ''}>EMPRESA</option>
                <option value="ADMIN" ${u.role === 'ADMIN' ? 'selected' : ''}>ADMIN</option>
              </select>
            </div>
          </div>
        `).join('');
      }
    }

    async function approveRequest(reqId, status) {
      const res = await fetch(`/api/v1/company-requests/${reqId}`, {
        method: 'PATCH',
        headers: { 'Authorization': `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
      });
      if (res.ok) {
        alert(`Solicitação ${status} com sucesso!`);
        fetchCurrentUser();
        loadAdminData();
      }
    }

    async function promoteUser(userId, newRole) {
      const res = await fetch(`/api/v1/admin/users/${userId}/role`, {
        method: 'PATCH',
        headers: { 'Authorization': `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole })
      });
      if (res.ok) {
        alert(`Papel do usuário atualizado para ${newRole}!`);
        loadAdminData();
      }
    }

    function openModal(id) {
      new bootstrap.Modal(document.getElementById(id)).show();
    }
    function closeModal(id) {
      const el = document.getElementById(id);
      const modal = bootstrap.Modal.getInstance(el);
      if (modal) modal.hide();
    }

    init();
  </script>
</body>
</html>
"""

# ==============================================================================
# 3. HANDLER HTTP E TRATAMENTO DAS ROTAS REST COM NEON (POSTGRESQL)
# ==============================================================================

# A classe precisa se chamar exatamente 'handler' para que a Vercel a reconheça
class handler(http.server.BaseHTTPRequestHandler):

    def get_clean_path(self):
      raw_path = self.headers.get('x-forwarded-uri') or self.headers.get('x-matched-path') or self.path
      parsed = urlparse(raw_path)
      path = parsed.path

      if path.startswith("/server.py"):
          path = path[10:]

      if not path:
          path = "/"

      return path

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', '*')
        self.end_headers()
        body = json.dumps(data, cls=CustomJSONEncoder).encode('utf-8')
        self.wfile.write(body)

    def send_html(self, html_content):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))

    def check_db_or_error(self):
        conn = get_db_connection()
        if not conn:
            self.send_json({"error": "DATABASE_URL não encontrada no ambiente ou falha na conexão com o Neon."}, 500)
            return None
        return conn

    def get_auth_user(self):
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            conn = get_db_connection()
            if not conn:
                return None
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT u.id, u.name, u.email, u.role
                        FROM sessions s
                        JOIN users u ON s.user_id = u.id
                        WHERE s.token = %s;
                    """, (token,))
                    return cur.fetchone()
            except Exception as e:
                print(f"Erro em get_auth_user: {e}")
                return None
            finally:
                conn.close()
        return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PATCH, OPTIONS')
        self.end_headers()

    def do_GET(self):
        path = self.get_clean_path()

        if path == "/" or path == "/index.html":
          return self.send_html(HTML_PAGE)

        user = self.get_auth_user()

        if path == "/api/v1/auth/me":
            if not user:
                return self.send_json({"error": "Não autenticado."}, 401)
            return self.send_json(user)

        conn = self.check_db_or_error()
        if not conn:
            return

        try:
            if path == "/api/v1/events":
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM events ORDER BY created_at DESC;")
                    self.send_json(cur.fetchall())

            elif path == "/api/v1/tickets":
                if not user:
                    return self.send_json({"error": "Não autenticado."}, 401)
                with conn.cursor() as cur:
                    if user['role'] == UserRole.ADMIN:
                        cur.execute("SELECT * FROM tickets ORDER BY created_at DESC;")
                    else:
                        cur.execute("SELECT * FROM tickets WHERE user_id = %s ORDER BY created_at DESC;", (user['id'],))
                    self.send_json(cur.fetchall())

            elif path == "/api/v1/company-requests/my-status":
                if not user:
                    return self.send_json({"error": "Não autenticado."}, 401)
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM company_requests WHERE user_id = %s ORDER BY created_at DESC LIMIT 1;", (user['id'],))
                    req = cur.fetchone()
                    if req:
                        return self.send_json({"status": req["status"], "request": req})
                    return self.send_json({"status": "NONE"})

            elif path == "/api/v1/company-requests":
                if not user or user["role"] != UserRole.ADMIN:
                    return self.send_json({"error": "Acesso negado. Requer perfil ADMIN."}, 403)
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM company_requests ORDER BY created_at DESC;")
                    self.send_json(cur.fetchall())

            elif path == "/api/v1/admin/stats":
                if not user or user["role"] != UserRole.ADMIN:
                    return self.send_json({"error": "Acesso negado. Requer perfil ADMIN."}, 403)
                with conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(SUM(total_amount), 0) as total_volume, COALESCE(SUM(platform_share_20), 0) as platform_share FROM financial_transactions;")
                    row = cur.fetchone()
                    self.send_json({"total_volume": row["total_volume"], "platform_share": row["platform_share"]})

            elif path == "/api/v1/admin/users":
                if not user or user["role"] != UserRole.ADMIN:
                    return self.send_json({"error": "Acesso negado. Requer perfil ADMIN."}, 403)
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name, email, role FROM users ORDER BY name ASC;")
                    self.send_json(cur.fetchall())

            else:
                self.send_json({"error": "Rota não encontrada"}, 404)

        except Exception as e:
            self.send_json({"error": f"Erro interno no servidor: {str(e)}"}, 500)
        finally:
            conn.close()

    def do_POST(self):
        path = self.get_clean_path()
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b'{}'
        data = json.loads(body.decode('utf-8')) if body else {}

        user = self.get_auth_user()
        conn = self.check_db_or_error()
        if not conn:
            return

        try:
            if path == "/api/v1/auth/register":
                name = data.get("name", "").strip()
                email = data.get("email", "").strip().lower()
                password = data.get("password", "").strip()

                if not name or not email or not password:
                    return self.send_json({"error": "Todos os campos são obrigatórios."}, 400)

                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM users WHERE LOWER(email) = %s;", (email,))
                    if cur.fetchone():
                        return self.send_json({"error": "Este e-mail já está cadastrado."}, 400)

                    new_user_id = str(uuid.uuid4())
                    pass_h = hash_password(password)
                    cur.execute("""
                        INSERT INTO users (id, name, email, pass_hash, role)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, name, email, role;
                    """, (new_user_id, name, email, pass_h, UserRole.PUBLICO))
                    new_user = cur.fetchone()

                    token = str(uuid.uuid4())
                    cur.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s);", (token, new_user_id))
                    conn.commit()

                    return self.send_json({"token": token, "user": new_user}, 201)

            elif path == "/api/v1/auth/login":
                email = data.get("email", "").strip().lower()
                pass_raw = data.get("password", "").strip()
                pass_hash = hash_password(pass_raw)

                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, name, email, role
                        FROM users
                        WHERE LOWER(email) = %s AND pass_hash = %s;
                    """, (email, pass_hash))
                    found = cur.fetchone()

                    if not found:
                        return self.send_json({"error": "E-mail ou senha incorretos."}, 401)

                    token = str(uuid.uuid4())
                    cur.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s);", (token, found["id"]))
                    conn.commit()

                    return self.send_json({"token": token, "user": found})

            elif path == "/api/v1/events":
                if not user or user["role"] not in [UserRole.EMPRESA, UserRole.ADMIN]:
                    return self.send_json({"error": "Usuário não possui permissão de EMPRESA para criar eventos."}, 403)

                price = data.get("price")
                stock = data.get("stock")
                if price is None or stock is None or float(price) < 0 or int(stock) < 0:
                    return self.send_json({"error": "Dados inválidos ou preço/estoque negativos."}, 422)

                new_id = str(uuid.uuid4())
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO events (id, company_id, company_name, title, category, price, stock, likes_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
                        RETURNING *;
                    """, (
                        new_id, user["id"], user["name"],
                        data.get("title", "Novo Evento"),
                        data.get("category", "Shows e Festivais"),
                        float(price), int(stock)
                    ))
                    new_event = cur.fetchone()
                    conn.commit()
                    return self.send_json(new_event, 201)

            elif path.startswith("/api/v1/events/") and path.endswith("/purchase"):
                if not user:
                    return self.send_json({"error": "Você precisa estar logado para comprar ingressos."}, 401)

                event_id = path.split("/")[4]
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM events WHERE id = %s FOR UPDATE;", (event_id,))
                    event = cur.fetchone()

                    if not event:
                        return self.send_json({"error": "Evento não encontrado."}, 404)

                    if event["stock"] <= 0:
                        return self.send_json({"error": "Ingressos esgotados para este evento"}, 400)

                    cur.execute("UPDATE events SET stock = stock - 1 WHERE id = %s;", (event_id,))

                    ticket_id = str(uuid.uuid4())
                    raw_seed = f"{ticket_id}-{user['id']}-{event_id}-{datetime.now(timezone.utc).timestamp()}"
                    qr_hash = f"QR-{hashlib.sha256(raw_seed.encode()).hexdigest()[:10].upper()}"

                    cur.execute("""
                        INSERT INTO tickets (id, user_id, event_id, event_title, qr_hash, is_used)
                        VALUES (%s, %s, %s, %s, %s, FALSE)
                        RETURNING *;
                    """, (ticket_id, user["id"], event_id, event["title"], qr_hash))
                    ticket = cur.fetchone()

                    total = float(event["price"])
                    company_share = round(total * 0.80, 2)
                    platform_share = round(total * 0.20, 2)
                    tx_id = str(uuid.uuid4())

                    cur.execute("""
                        INSERT INTO financial_transactions (id, ticket_id, total_amount, platform_share_20, company_share_80)
                        VALUES (%s, %s, %s, %s, %s);
                    """, (tx_id, ticket_id, total, platform_share, company_share))

                    conn.commit()

                    return self.send_json({
                        "ticket": ticket,
                        "financial_split": {
                            "total_amount": total,
                            "company_share_80": company_share,
                            "platform_share_20": platform_share
                        }
                    }, 201)

            elif path == "/api/v1/tickets/validate":
                qr_hash = data.get("qr_hash", "").strip()
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM tickets WHERE qr_hash = %s;", (qr_hash,))
                    ticket = cur.fetchone()

                    if not ticket:
                        return self.send_json({"error": "Código Hash inexistente ou inválido."}, 404)

                    if ticket["is_used"]:
                        return self.send_json({"error": "ALERTA: Ingresso já utilizado anteriormente na portaria"}, 400)

                    validated_at = datetime.now(timezone.utc)
                    cur.execute("UPDATE tickets SET is_used = TRUE, validated_at = %s WHERE id = %s;", (validated_at, ticket["id"]))
                    conn.commit()

                    return self.send_json({
                        "status": "VALIDATED",
                        "message": "Entrada liberada com sucesso!",
                        "event_title": ticket["event_title"],
                        "validated_at": validated_at.isoformat()
                    }, 200)

            elif path == "/api/v1/company-requests":
                if not user:
                    return self.send_json({"error": "Você precisa estar autenticado."}, 401)

                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM company_requests WHERE user_id = %s AND status = 'PENDENTE';", (user["id"],))
                    if cur.fetchone():
                        return self.send_json({"error": "Você já possui uma solicitação de parceria pendente em análise."}, 400)

                    cur.execute("SELECT COUNT(*) as count FROM company_requests;")
                    count = cur.fetchone()["count"]
                    req_id = f"REQ-{count + 101}"

                    cur.execute("""
                        INSERT INTO company_requests (id, user_id, company_name, cnpj, email, description, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'PENDENTE')
                        RETURNING *;
                    """, (
                        req_id, user["id"],
                        data.get("company_name", ""),
                        data.get("cnpj", ""),
                        user["email"],
                        data.get("description", "")
                    ))
                    req = cur.fetchone()
                    conn.commit()
                    return self.send_json(req, 201)

            else:
                self.send_json({"error": "Rota não encontrada"}, 404)

        except Exception as e:
            self.send_json({"error": f"Erro interno no servidor: {str(e)}"}, 500)
        finally:
            conn.close()

    def do_PATCH(self):
        path = self.get_clean_path()
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b'{}'
        data = json.loads(body.decode('utf-8')) if body else {}

        user = self.get_auth_user()
        conn = self.check_db_or_error()
        if not conn:
            return

        try:
            if path.startswith("/api/v1/company-requests/"):
                if not user or user["role"] != UserRole.ADMIN:
                    return self.send_json({"error": "Acesso negado. Requer perfil ADMIN."}, 403)

                req_id = path.split("/")[4]
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM company_requests WHERE id = %s;", (req_id,))
                    req = cur.fetchone()
                    if not req:
                        return self.send_json({"error": "Solicitação não encontrada"}, 404)

                    status = data.get("status", "APROVADO")
                    cur.execute("UPDATE company_requests SET status = %s WHERE id = %s RETURNING *;", (status, req_id))
                    updated_req = cur.fetchone()

                    if status == "APROVADO":
                        cur.execute("UPDATE users SET role = 'EMPRESA' WHERE id = %s;", (req["user_id"],))

                    conn.commit()
                    return self.send_json({"message": f"Solicitação {status} com sucesso!", "request": updated_req}, 200)

            elif path.startswith("/api/v1/admin/users/") and path.endswith("/role"):
                if not user or user["role"] != UserRole.ADMIN:
                    return self.send_json({"error": "Acesso negado. Requer perfil ADMIN."}, 403)

                target_user_id = path.split("/")[5]
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM users WHERE id = %s;", (target_user_id,))
                    target_user = cur.fetchone()
                    if not target_user:
                        return self.send_json({"error": "Usuário não encontrado"}, 404)

                    new_role = data.get("role")
                    if new_role in [UserRole.PUBLICO, UserRole.EMPRESA, UserRole.ADMIN]:
                        cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING id, name, email, role;", (new_role, target_user_id))
                        updated_user = cur.fetchone()
                        conn.commit()
                        return self.send_json(updated_user, 200)
                    else:
                        return self.send_json({"error": "Papel inválido"}, 400)

        except Exception as e:
            self.send_json({"error": f"Erro interno no servidor: {str(e)}"}, 500)
        finally:
            conn.close()

# ==============================================================================
# 4. INICIALIZAÇÃO LOCAL (PORTA 8000)
# ==============================================================================

if __name__ == "__main__":
    PORT = 8000
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"🚀 Servidor All Tickets rodando em http://localhost:{PORT}")
        print("💡 Conectado ao Neon PostgreSQL! Teste o fluxo no navegador.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor encerrado.")