# Exporta do modelo "Produtos" aberto no Power BI Desktop as tabelas de apoio
# usadas na análise de cupons (produto -> categoria e mapa mãe/complementar).
# Só lê o modelo (consultas DAX). Não faz refresh nem altera nada.
#
# Uso:  powershell -ExecutionPolicy Bypass -File exportar_apoio_powerbi.ps1
# Requer o Power BI Desktop aberto com o arquivo Produtos.pbix.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
# saída fixa em ..\dados (pasta fora do Git); nunca recebe caminho de fora
$saida = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\dados"))
New-Item -ItemType Directory -Force $saida | Out-Null

$pbi = (Get-Process PBIDesktop -ErrorAction Stop | Select-Object -First 1).Path
$dll = Join-Path (Split-Path $pbi) "Microsoft.PowerBI.AdomdClient.dll"
Add-Type -Path $dll

# A porta do modelo local muda a cada abertura do Power BI; descobre pela porta
# em escuta do processo msmdsrv (o mecanismo de análise embutido no Desktop).
$msmdsrv = Get-Process msmdsrv -ErrorAction Stop | Select-Object -First 1
$porta = (Get-NetTCPConnection -OwningProcess $msmdsrv.Id -State Listen -ErrorAction Stop |
    Select-Object -First 1).LocalPort
if (-not $porta -or $porta -notmatch '^\d{2,5}$') { throw "Não achei a porta do modelo do Power BI Desktop." }
# só conecta no próprio computador (o modelo do Desktop não aceita acesso remoto)
Write-Host "Modelo local na porta $porta"

$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$porta")
$conn.Open()

function Exportar($nome, $dax) {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $dax
    $cmd.CommandTimeout = 600
    $rd = $cmd.ExecuteReader()
    $caminho = Join-Path $saida $nome
    $sw = New-Object System.IO.StreamWriter($caminho, $false, (New-Object System.Text.UTF8Encoding($true)))
    $cols = 0..($rd.FieldCount - 1) | ForEach-Object {
        $n = $rd.GetName($_); if ($n -match '\[(.+)\]$') { $matches[1] } else { $n }
    }
    $sw.WriteLine(($cols | ForEach-Object { '"' + $_ + '"' }) -join ";")
    $linhas = 0
    while ($rd.Read()) {
        $v = 0..($rd.FieldCount - 1) | ForEach-Object {
            $x = $rd.GetValue($_)
            if ($null -eq $x -or $x -is [DBNull]) { '' }
            elseif ($x -is [double] -or $x -is [decimal]) { ([double]$x).ToString([Globalization.CultureInfo]::InvariantCulture) }
            elseif ($x -is [datetime]) { $x.ToString("yyyy-MM-dd") }
            else { '"' + ([string]$x).Replace('"', '""') + '"' }
        }
        $sw.WriteLine($v -join ";")
        $linhas++
    }
    $sw.Close(); $rd.Close()
    Write-Host ("{0}: {1} linhas" -f $nome, $linhas)
}

# 1) Produtos que aparecem nos cupons, com a hierarquia comercial.
Exportar "produtos_cupom.csv" @"
EVALUATE
VAR _ids = SELECTCOLUMNS(
    VALUES(Cupom[PRODUTO]),
    "id", VALUE(LEFT(Cupom[PRODUTO], SEARCH(" - ", Cupom[PRODUTO]) - 1))
)
RETURN
SELECTCOLUMNS(
    FILTER(dim_produto, dim_produto[id_produto] IN _ids),
    "id_produto", dim_produto[id_produto],
    "produto", dim_produto[produto],
    "id_categoria", dim_produto[id_categoria_comercial],
    "categoria", dim_produto[categoria_comercial],
    "departamento", dim_produto[departamento],
    "secao", dim_produto[secao],
    "setor", dim_produto[setor],
    "marca", dim_produto[marca],
    "tipo_produto", dim_produto[Tipo Produto]
)
"@

# 2) Mapa categoria mãe -> categoria complementar (com relação, força e motivo).
Exportar "mapa_mae_complementar.csv" @"
EVALUATE
SELECTCOLUMNS(
    Mapa_Mae_Complementar,
    "grupo", Mapa_Mae_Complementar[Grupo],
    "id_categoria_mae", Mapa_Mae_Complementar[id_categoria_mae],
    "categoria_mae", Mapa_Mae_Complementar[Categoria Mãe],
    "id_categoria_complementar", Mapa_Mae_Complementar[id_categoria_complementar],
    "categoria_complementar", Mapa_Mae_Complementar[Categoria Complementar],
    "relacao", Mapa_Mae_Complementar[Relação],
    "forca", Mapa_Mae_Complementar[Força],
    "motivo", Mapa_Mae_Complementar[Motivo]
)
"@

# 3) Papel de cada categoria (mãe/complementar/etc.).
Exportar "categorias.csv" @"
EVALUATE
SELECTCOLUMNS(
    dCategoria,
    "id_categoria", dCategoria[id_categoria_comercial],
    "categoria", dCategoria[categoria_comercial],
    "papel", dCategoria[Papel]
)
"@

# 4) Venda diária por produto da loja 20 (a fato f_Venda_atual traz a rede toda, 346 filiais).
#    Serve para comparar a venda antes x durante o encarte.
Exportar "venda_dia_produto_loja20.csv" @"
EVALUATE
SUMMARIZECOLUMNS(
    f_Venda_atual[dia_venda],
    f_Venda_atual[id_produto],
    TREATAS({20}, f_Venda_atual[id_filial]),
    "venda", SUM(f_Venda_atual[venda]),
    "quantidade", SUM(f_Venda_atual[quantidade]),
    "lucro", SUM(f_Venda_atual[lucro])
)
"@

# 5) Hierarquia comercial dos produtos vendidos na loja 20 ou presentes na pesquisa de preço.
Exportar "produtos_loja20.csv" @"
EVALUATE
VAR _vendidos = CALCULATETABLE(VALUES(f_Venda_atual[id_produto]), f_Venda_atual[id_filial] = 20)
VAR _pesquisados = VALUES(Pesquisa[id_produto])
RETURN
SELECTCOLUMNS(
    FILTER(dim_produto, dim_produto[id_produto] IN _vendidos || dim_produto[id_produto] IN _pesquisados),
    "id_produto", dim_produto[id_produto],
    "produto", dim_produto[produto],
    "id_categoria", dim_produto[id_categoria_comercial],
    "categoria", dim_produto[categoria_comercial],
    "departamento", dim_produto[departamento],
    "secao", dim_produto[secao],
    "setor", dim_produto[setor],
    "marca", dim_produto[marca],
    "tipo_produto", dim_produto[Tipo Produto]
)
"@

$conn.Close()
Write-Host "Pronto: arquivos em $saida"
