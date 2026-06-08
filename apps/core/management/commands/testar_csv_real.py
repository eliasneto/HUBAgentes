from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Testa o agente Groq com o CSV real do usuario."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from apps.agentes_ia.models import AgenteIA
        from apps.processamentos.services.operational_execution import criar_e_iniciar_processamento_para_agente
        from apps.processamentos.models import ProcessingInputSourceType, ProcessingOutputFormat
        from django.core.files.base import ContentFile

        User = get_user_model()
        admin = User.objects.filter(is_superuser=True).first()
        agente = AgenteIA.objects.filter(slug__icontains='groq').first()

        self.stdout.write(f"Agente: {agente.nome} | Modelo: {agente.modelo_preferencial or agente.ai_provider_integration.default_model}")

        csv_bytes = b"""01TC0361,,,
Cod.Empregado,Cod. Evento,Referencia,Valor do Evento
1022,069,,1630
1022,299,,195.425
0968,069,,1630
0968,299,,195.425
1024,069,,1630
1024,299,,195.425
0281,069,,1630
0281,299,,717.656
0517,069,,1650
0517,299,,1254.046
0306,069,,1650
0306,299,,795.77
0282,069,,1650
0282,299,,932.5157
0286,069,,1650
0286,299,,1243.872
1023,069,,1630
1023,299,,195.425
0426,069,,2000
0426,299,,412.3758
0303,069,,10905.85
0303,299,,8765.876
0598,069,,12285.16
0598,299,,9965.875
Z,86,,154386.93
"""
        cleaned_data = {
            "input_source_type": ProcessingInputSourceType.UPLOAD_AT_EXECUTION,
            "output_format": ProcessingOutputFormat.JSON,
            "arquivo_execucao_upload": ContentFile(csv_bytes, name="folha_tc.csv"),
            "local_relative_input_path": "",
            "local_storage_integration": None,
            "folder_source": None,
        }

        try:
            proc = criar_e_iniciar_processamento_para_agente(agente=agente, actor=admin, cleaned_data=cleaned_data)
            proc.refresh_from_db()
            self.stdout.write(f"Status: {proc.status}")
            self.stdout.write(f"Tokens: {proc.total_tokens}")
            if proc.mensagem_erro_tecnico:
                self.stdout.write(f"Erro: {proc.mensagem_erro_tecnico[:400]}")
            if proc.arquivo_saida:
                import zipfile, json, io
                proc.arquivo_saida.open("rb")
                raw = proc.arquivo_saida.read()
                try:
                    zf = zipfile.ZipFile(io.BytesIO(raw))
                    content = zf.read(zf.namelist()[0])
                except Exception:
                    content = raw
                try:
                    data = json.loads(content)
                    self.stdout.write(self.style.SUCCESS("JSON VALIDO"))
                    self.stdout.write(f"Funcionarios: {len(data.get('funcionarios', []))}")
                    self.stdout.write(f"Soma total: {data.get('resumo', {}).get('soma_total_valores')}")
                except Exception:
                    self.stdout.write(f"Saida (300 chars): {content[:300]}")
        except Exception as exc:
            self.stderr.write(f"ERRO: {exc}")
