import logging

from django.conf import settings
from django.core import checks
from django.db import models

logger = logging.getLogger(__name__)


def _build_fernet():
    """Retorna instancia Fernet ou None se a chave nao estiver configurada."""
    from cryptography.fernet import Fernet

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


@checks.register(checks.Tags.security)
def check_field_encryption_key(app_configs, **kwargs):
    """System check: garante que FIELD_ENCRYPTION_KEY esta configurada no startup."""
    errors = []
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        errors.append(
            checks.Warning(
                "FIELD_ENCRYPTION_KEY nao esta configurada.",
                hint=(
                    "Campos sensiveis (api_key, credentials_json) serao armazenados "
                    "sem criptografia. Defina FIELD_ENCRYPTION_KEY no .env de producao. "
                    "Gere com: python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\""
                ),
                id="core.W001",
            )
        )
    return errors


class EncryptedFieldMixin:
    """
    Criptografa o valor em repouso usando Fernet (AES-128-CBC + HMAC-SHA256).
    Requer FIELD_ENCRYPTION_KEY em settings: chave URL-safe base64 de 32 bytes.
    Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Se a chave nao estiver configurada, o valor e armazenado sem criptografia com aviso de log.
    """

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        fernet = _build_fernet()
        if fernet is None:
            return value
        try:
            return fernet.decrypt(value.encode()).decode()
        except Exception:
            # Valor ainda nao criptografado (dados legados) — retorna como esta.
            logger.warning(
                "Campo criptografado recebeu valor que nao pode ser decifrado. "
                "Re-salve o registro para aplicar criptografia."
            )
            return value

    def get_prep_value(self, value):
        if not value:
            return value
        fernet = _build_fernet()
        if fernet is None:
            logger.error(
                "FIELD_ENCRYPTION_KEY nao configurada. Salvando campo sensiivel "
                "sem criptografia. Defina a variavel de ambiente."
            )
            return value
        try:
            # Evita re-criptografar valor ja criptografado (identificado pelo prefixo Fernet).
            fernet.decrypt(value.encode())
            return value
        except Exception:
            pass
        return fernet.encrypt(value.encode()).decode()


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    """TextField com criptografia transparente em repouso."""


class EncryptedCharField(EncryptedFieldMixin, models.TextField):
    """Armazena CharField criptografado como TextField (o valor cifrado e maior que o original)."""
