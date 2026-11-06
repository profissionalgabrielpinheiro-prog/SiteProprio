import pytest

from cupons.encarte import volume_necessario


def test_matriz_da_imagem_de_referencia():
    """Preço líquido R$ 100, custo R$ 70, volume 100 un: margem a preservar R$ 3.000."""
    custo, preco, vol = 70.0, 100.0, 100.0
    esperado = {5: 120.0, 10: 150.0, 15: 200.0}      # do quadro "10% de desconto exige 50% mais volume"
    for desconto, volume in esperado.items():
        promo = preco * (1 - desconto / 100)
        nec = volume_necessario(vol, preco - custo, promo - custo)
        assert nec == pytest.approx(volume)
        assert (preco - custo) * vol == pytest.approx(3000)
        assert (promo - custo) * nec == pytest.approx(3000)       # a margem total é preservada


def test_sem_margem_nenhum_volume_compensa():
    assert volume_necessario(100, 30, 0) is None
    assert volume_necessario(100, 30, -5) is None      # preço abaixo do custo
    assert volume_necessario(100, 0, 10) is None       # margem normal já era zero
    assert volume_necessario(100, None, 10) is None


def test_sem_desconto_mantem_volume():
    assert volume_necessario(80, 30, 30) == pytest.approx(80)
