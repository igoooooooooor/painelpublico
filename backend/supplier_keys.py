"""Chave de fornecedor pessoa física sem expor o CPF.

O CPF tem só 10⁹ combinações: um SHA-256 puro (``cpf-sha256:``, usado até out/2026) se desfaz testando todas,
em minutos. A chave pública passa a ser ``cpf-hmac:`` + HMAC-SHA256(segredo, SHA-256 do CPF), e o segredo
nunca sai da máquina que coleta e serve os dados: nem Git, nem release, nem snapshot.

Calcular o HMAC sobre o SHA-256 antigo (e não sobre o CPF) permite converter as chaves já gravadas sem
conhecer nenhum CPF; a nota coletada depois da migração ganha exatamente a mesma chave.

Segredo: variável ``PAINEL_SUPPLIER_SECRET`` ou o arquivo ``supplier-key.secret`` ao lado do banco
(``data/`` no computador, ``/opt/painel/data`` no servidor), criado na primeira vez em que é preciso.
Com outro segredo, a mesma pessoa ganha outra chave; ``make deploy-data`` leva o arquivo junto do banco.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

from .config import DB_PATH

LEGACY_PREFIX = 'cpf-sha256:'
PREFIX = 'cpf-hmac:'
SECRET_FILE = 'supplier-key.secret'
MIN_SECRET_LENGTH = 32
FINGERPRINT_ID = re.compile(r'^(.+):fingerprint:([0-9a-f]{64}):(\d+)$')
_cache: dict[tuple, bytes] = {}


def _secret_path() -> Path:
    return DB_PATH.parent / SECRET_FILE


def secret() -> bytes:
    """Segredo da chave; criado com 64 caracteres aleatórios se ainda não existir."""
    configured = os.environ.get('PAINEL_SUPPLIER_SECRET', '').strip()
    path = _secret_path()
    cache_key = (configured, str(path))
    if cache_key in _cache:
        return _cache[cache_key]
    if configured:
        value = configured
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            value = path.read_text(encoding='ascii').strip()
        else:
            value = secrets.token_hex(32)
            with os.fdopen(descriptor, 'w', encoding='ascii') as handle:
                handle.write(value + '\n')
    if len(value) < MIN_SECRET_LENGTH:
        raise RuntimeError(f'Segredo da chave de fornecedor curto demais (mínimo {MIN_SECRET_LENGTH} caracteres): '
                           'confira PAINEL_SUPPLIER_SECRET ou ' + str(path))
    _cache[cache_key] = value.encode('utf-8')
    return _cache[cache_key]


def _keyed(value: str) -> str:
    return hmac.new(secret(), value.encode('ascii'), hashlib.sha256).hexdigest()


def public_key(key):
    """Chave gravável: a antiga ``cpf-sha256:`` vira ``cpf-hmac:``; as demais passam como estão."""
    if isinstance(key, str) and key.startswith(LEGACY_PREFIX):
        return PREFIX + _keyed(key[len(LEGACY_PREFIX):])
    return key


def cpf_key(cpf_digits: str) -> str:
    """Chave de um fornecedor identificado por CPF (11 dígitos), igual à da chave antiga convertida."""
    return public_key(LEGACY_PREFIX + hashlib.sha256(cpf_digits.encode('ascii')).hexdigest())


def _fingerprint_id(expense_id: str) -> str:
    """O ID por conteúdo de uma nota sem número na fonte inclui a chave do fornecedor; o antigo é convertido igual."""
    match = FINGERPRINT_ID.fullmatch(expense_id)
    if not match:
        return expense_id
    return f'{match[1]}:fingerprint:{_keyed("fingerprint:" + match[2])}:{match[3]}'


def legacy_count(db) -> int:
    pattern = LEGACY_PREFIX + '%'
    return sum(db.execute(f'SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?', (pattern,)).fetchone()[0]
               for table, column in (('suppliers', 'key'), ('expenses', 'supplierKey'),
                                     ('quota_history_notes', 'supplierKey')))


def rekey_legacy(db) -> int:
    """Troca as chaves ``cpf-sha256:`` gravadas pelas ``cpf-hmac:``, sem apagar nenhuma nota.

    Devolve quantos fornecedores mudaram; quem chama refaz os agregados e os alertas (o ID do alerta de
    concentração inclui a chave)."""
    pattern = LEGACY_PREFIX + '%'
    keys = sorted({row[0] for table, column in (('suppliers', 'key'), ('expenses', 'supplierKey'),
                                                 ('quota_history_notes', 'supplierKey'))
                   for row in db.execute(f'SELECT DISTINCT {column} FROM {table} WHERE {column} LIKE ?', (pattern,))})
    if not keys:
        return 0
    pairs = [(public_key(key), key) for key in keys]
    db.executemany('INSERT OR IGNORE INTO suppliers(key,name,cnpj) SELECT ?,name,cnpj FROM suppliers WHERE key=?', pairs)
    renamed = [(_fingerprint_id(identifier), identifier) for (identifier,) in db.execute(
        "SELECT id FROM expenses WHERE supplierKey LIKE ? AND id LIKE '%:fingerprint:%'", (pattern,))]
    db.executemany('UPDATE expenses SET id=? WHERE id=?', [pair for pair in renamed if pair[0] != pair[1]])
    db.executemany('UPDATE expenses SET supplierKey=? WHERE supplierKey=?', pairs)
    db.executemany('UPDATE quota_history_notes SET supplierKey=? WHERE supplierKey=?', pairs)
    db.executemany('DELETE FROM suppliers WHERE key=?', [(key,) for key in keys])
    return len(keys)
