Temos 3 opções de função objetivo (escolhida dentro do código).

        objective_type = "weighted_loss"
        # objective_type = "new_coils_value"
        # objective_type = "non_reusable_loss"

Para cada uma delas, executar para todas as instâncias. Quando terminar de executar com a primeira função objetivo, você deve rodar o script generate_results_tables.

Antes de rodar com o próximo objetivo, você deve copiar as pastas data, output e results em outro canto (pois vai sobrescrever os resultados). Uma ideia mais segura é manter uma pasta de projeto para cada função objetivo.

Com isso, acredito que temos tudo para nossa seção de resultados do artigo. Para a dissertação, precisaremos ainda avançar com diferentes planos de corte por bobina.