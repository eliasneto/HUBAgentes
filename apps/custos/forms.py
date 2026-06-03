from django import forms

from apps.custos.models import ConfiguracaoFinanceira, PrecificacaoModelo
from apps.integracoes.models import AIProviderIntegration


class PrecificacaoModeloForm(forms.ModelForm):
    nome_modelo = forms.ChoiceField(choices=[])

    class Meta:
        model = PrecificacaoModelo
        fields = ["nome_modelo", "preco_input_por_milhao", "preco_output_por_milhao", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        integracoes = (
            AIProviderIntegration.objects.filter(default_model__gt="")
            .order_by("nome")
        )

        choices = [("", "— Selecione uma integração —")]
        seen = set()
        for integracao in integracoes:
            model = integracao.default_model
            if model not in seen:
                choices.append((model, f"{integracao.nome}  —  {model}"))
                seen.add(model)

        # Mantém o valor atual se não estiver na lista (ex: integração removida)
        if self.instance and self.instance.pk and self.instance.nome_modelo:
            if self.instance.nome_modelo not in seen:
                choices.append((
                    self.instance.nome_modelo,
                    f"{self.instance.nome_modelo}",
                ))

        self.fields["nome_modelo"].choices = choices

        for name, field in self.fields.items():
            if name == "ativo":
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} portal-input".strip()
            field.widget.attrs.setdefault("autocomplete", "off")


class ConfiguracaoFinanceiraForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoFinanceira
        fields = ["cotacao_dolar"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} portal-input".strip()
            field.widget.attrs.setdefault("autocomplete", "off")
