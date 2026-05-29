import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


class EncryptedFieldMixin:
    """
    Criptografa o valor em repouso usando Fernet (AES-128-CBC + HMAC-SHA256).
    Requer FIELD_ENCRYPTION_KEY em settings: chave URL-safe base64 de 32 bytes.
    Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """

    def _get_fernet(self):
        from cryptography.fernet import Fernet

        key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
        if not key:
            raise ValueError(
                "FIELD_ENCRYPTION_KEY nao configurada. "
                "Defina a variavel de ambiente antes de usar campos criptografados."
            )
        return Fernet(key.encode() if isinstance(key, str) else key)

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return self._get_fernet().decrypt(value.encode()).decode()
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
        try:
            # Evita re-criptografar valor ja criptografado (identificado pelo prefixo Fernet).
            self._get_fernet().decrypt(value.encode())
            return value
        except Exception:
            pass
        return self._get_fernet().encrypt(value.encode()).decode()


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    """TextField com criptografia transparente em repouso."""


class EncryptedCharField(EncryptedFieldMixin, models.TextField):
    """Armazena CharField criptografado como TextField (o valor cifrado e maior que o original)."""
