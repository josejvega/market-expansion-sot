const marketAnalysis = {
    breakEven(fixed, variableRatio, ticket, capacity = null) {
        if (![fixed, variableRatio].every(value => typeof value === 'number' && Number.isFinite(value)) || fixed < 0 || variableRatio < 0 || variableRatio >= 1) return null;
        const revenue = fixed / (1 - variableRatio);
        const members = typeof ticket === 'number' && ticket > 0 ? Math.ceil(revenue / ticket) : null;
        return {revenue, members, exactMembers: members == null ? null : revenue / ticket, capacityExceeded: members != null && capacity != null && members > capacity};
    },
   simulate(study, settings) {
    const weights = {
        population: Number(settings.weights.population),
        income: Number(settings.weights.income),
        growth: Number(settings.weights.growth),
    };

    if (
        Object.values(weights).some(
            value => !Number.isFinite(value) || value < 0
        )
    ) {
        return {
            error: 'Los pesos deben ser números no negativos.',
        };
    }

    if (Object.values(weights).every(value => value === 0)) {
        return {
            error: 'Al menos uno de los pesos debe ser mayor que cero.',
        };
    }

    /*
     * Solo pueden entrar en K-means los municipios con las tres
     * variables necesarias y población objetivo positiva.
     */
    const usable = study.municipalities
        .filter(row =>
            Number.isFinite(row.target_population) &&
            row.target_population > 0 &&
            Number.isFinite(row.income_eur) &&
            Number.isFinite(row.growth_pct)
        )
        .map(row => ({
            ...row,
            rawFeatures: [
                Math.log1p(row.target_population),
                row.income_eur,
                row.growth_pct,
            ],
        }));

    if (usable.length < 4) {
        return {
            error: 'No hay suficientes municipios completos para formar cuatro clusters.',
        };
    }

    /*
     * Media y desviación típica de cada variable.
     */
    const featureCount = 3;

    const means = Array.from(
        {length: featureCount},
        (_, featureIndex) =>
            usable.reduce(
                (total, row) => total + row.rawFeatures[featureIndex],
                0
            ) / usable.length
    );

    const deviations = Array.from(
        {length: featureCount},
        (_, featureIndex) => {
            const variance =
                usable.reduce((total, row) => {
                    const difference =
                        row.rawFeatures[featureIndex] - means[featureIndex];

                    return total + difference * difference;
                }, 0) / usable.length;

            return Math.sqrt(variance);
        }
    );

    /*
     * Para que los controles representen pesos de la distancia
     * euclídea cuadrática, cada variable se multiplica por sqrt(peso).
     *
     * d² = wp·Δzp² + wr·Δzr² + wc·Δzc²
     */
    const weightVector = [
        Math.sqrt(weights.population),
        Math.sqrt(weights.income),
        Math.sqrt(weights.growth),
    ];

    const points = usable.map(row => ({
        ...row,
        features: row.rawFeatures.map((value, featureIndex) => {
            const deviation = deviations[featureIndex];

            const standardized =
                deviation === 0
                    ? 0
                    : (value - means[featureIndex]) / deviation;

            return standardized * weightVector[featureIndex];
        }),
    }));

    const squaredDistance = (left, right) =>
        left.reduce((total, value, index) => {
            const difference = value - right[index];
            return total + difference * difference;
        }, 0);

    /*
     * Inicialización determinista:
     * 1. Primer centroide: municipio con menor código.
     * 2. Siguientes centroides: punto más alejado de los ya elegidos.
     *
     * Evita que el resultado cambie aleatoriamente al mover un slider.
     */
    const sortedPoints = [...points].sort(
        (left, right) => String(left.id).localeCompare(String(right.id))
    );

    const centroids = [[...sortedPoints[0].features]];

    while (centroids.length < 4) {
        let selectedPoint = null;
        let selectedDistance = -1;

        for (const point of sortedPoints) {
            const nearestDistance = Math.min(
                ...centroids.map(centroid =>
                    squaredDistance(point.features, centroid)
                )
            );

            if (nearestDistance > selectedDistance) {
                selectedPoint = point;
                selectedDistance = nearestDistance;
            }
        }

        centroids.push([...selectedPoint.features]);
    }

    let assignments = new Array(points.length).fill(-1);

    /*
     * Iteraciones de K-means.
     */
    for (let iteration = 0; iteration < 100; iteration++) {
        const nextAssignments = points.map(point => {
            let nearestCluster = 0;
            let nearestDistance = Infinity;

            centroids.forEach((centroid, clusterIndex) => {
                const distance = squaredDistance(
                    point.features,
                    centroid
                );

                if (distance < nearestDistance) {
                    nearestDistance = distance;
                    nearestCluster = clusterIndex;
                }
            });

            return nearestCluster;
        });

        const converged = nextAssignments.every(
            (cluster, index) => cluster === assignments[index]
        );

        assignments = nextAssignments;

        const sums = Array.from(
            {length: 4},
            () => Array(featureCount).fill(0)
        );

        const counts = Array(4).fill(0);

        points.forEach((point, pointIndex) => {
            const cluster = assignments[pointIndex];
            counts[cluster] += 1;

            point.features.forEach((value, featureIndex) => {
                sums[cluster][featureIndex] += value;
            });
        });

        for (let cluster = 0; cluster < 4; cluster++) {
            if (counts[cluster] === 0) {
                continue;
            }

            centroids[cluster] = sums[cluster].map(
                value => value / counts[cluster]
            );
        }

        if (converged) {
            break;
        }
    }

    /*
     * Presión competitiva:
     * competencia ponderada / población objetivo × 10.000.
     */
    const clustered = points.map((point, index) => ({
        ...point,
        scenarioCluster: assignments[index],
        competitionRate:
            Number.isFinite(point.competitors_weighted) &&
            point.target_population > 0
                ? (
                    point.competitors_weighted /
                    point.target_population
                ) * 10000
                : null,
    }));

    /*
     * Media de presión competitiva dentro de cada cluster.
     */
    const clusterMeans = new Map();

    for (let cluster = 0; cluster < 4; cluster++) {
        const values = clustered
            .filter(row => row.scenarioCluster === cluster)
            .map(row => row.competitionRate)
            .filter(value => Number.isFinite(value));

        clusterMeans.set(
            cluster,
            values.length
                ? values.reduce((total, value) => total + value, 0) /
                  values.length
                : null
        );
    }

    /*
     * Candidato si su presión competitiva es inferior a la media
     * de su nuevo cluster.
     */
    const evaluated = clustered.map(row => {
        const clusterMean = clusterMeans.get(row.scenarioCluster);

        return {
            ...row,
            clusterMean,
            scenarioCandidate:
                Number.isFinite(row.competitionRate) &&
                Number.isFinite(clusterMean) &&
                row.competitionRate < clusterMean,
        };
    });

    const candidates = evaluated.filter(
        row => row.scenarioCandidate
    );

    /*
     * Mantiene la facturación publicada por el módulo de negocio.
     * El simulador cambia los clusters y la condición de candidato,
     * pero no inventa otra fórmula económica.
     */
    const selection = candidates
        .filter(row => Number.isFinite(row.annual_revenue_eur))
        .sort(
            (left, right) =>
                right.annual_revenue_eur - left.annual_revenue_eur ||
                String(left.id).localeCompare(String(right.id))
        )
        .slice(0, 5);

    const selectionTotal =
        selection.length === 5
            ? selection.reduce(
                (total, row) => total + row.annual_revenue_eur,
                0
            )
            : null;

    return {
        selection,
        selectionTotal,
        candidateCount: candidates.length,
        excluded:
            study.municipalities.length - usable.length,
        clusterMeans,
    };
}
};
if (typeof module !== 'undefined' && module.exports) module.exports = marketAnalysis;
if (typeof window !== 'undefined') window.marketAnalysis = marketAnalysis;

if (typeof document !== 'undefined') {
    const readNumber = id => el(id).value.trim() === '' ? null : Number(el(id).value);
    const setValue = (id, value) => {el(id).value = value ?? '';};
    const checks = new Map((DATA.market_checks || []).map(row => [row.municipality_id, row]));
    const zeroMarkets = rows.filter(row => row.competitor_count === 0);
    const confirmed = zeroMarkets.filter(row => checks.get(row.id)?.status === 'confirmed_zero');
    const found = zeroMarkets.filter(row => checks.get(row.id)?.status === 'competitors_found');
    el('competition-answer').textContent = `${zeroMarkets.length} municipios sin competencia registrada; ${selected.filter(row => row.competitor_count === 0).length} entre los cinco propuestos. Ausencia corroborada con evidencia: ${confirmed.length}. Competidores encontrados al contrastar: ${found.length}. Sin conclusion: ${zeroMarkets.length - confirmed.length - found.length}. La ausencia real no puede deducirse del recuento OSM; las comprobaciones solo valen para su fecha y ambito.`;
    el('market-checks').innerHTML = zeroMarkets.filter(row => checks.has(row.id)).map(row => {
        const check = checks.get(row.id);
        const status = {confirmed_zero: 'Ausencia corroborada', competitors_found: 'Competencia encontrada', unresolved: 'Sin resolver'}[check.status];
        return `<li>${escapeHtml(row.name)}: ${status}. ${escapeHtml(check.finding)} ${escapeHtml(check.scope)} ${escapeHtml(check.checked_date)} ${safeLink(check.source_url ? 'Evidencia' : '', check.source_url)}</li>`;
    }).join('');
    el('selection-answer').textContent = meta.baseline_description + ' ' + meta.selection_description + ' ' + meta.methodology + ' Una mayor facturacion de escenario no demuestra mejores ventas reales.';

    const finance = DATA.finance || {};
    setValue('fixed-cost', finance.annual_fixed_cost_eur);
    setValue('variable-cost', finance.variable_cost_ratio == null ? null : finance.variable_cost_ratio * 100);
    setValue('finance-ticket', finance.annual_ticket_eur);
    setValue('capacity', finance.capacity_members);
    function updateFinance() {
        const fixed = readNumber('fixed-cost'), variable = readNumber('variable-cost');
        const ticket = readNumber('finance-ticket'), capacity = readNumber('capacity');
        const result = marketAnalysis.breakEven(fixed, variable == null ? null : variable / 100, ticket, capacity);
        el('breakeven-revenue').textContent = result ? money(result.revenue) : 'n/d';
        el('breakeven-members').textContent = result ? fmt(result.members) : 'n/d';
        el('profitability-answer').textContent = result ? `El umbral operativo es ${money(result.revenue)} al ano, con ${money(fixed)} de costes fijos y ${fmt(variable, 1)} % de costes variables sobre ventas. ` + (result.members == null ? 'Sin cuota anual no se calcula el numero de abonados.' : `Equivale a ${fmt(result.members)} abonados a la cuota indicada.`) : 'No se puede determinar sin costes fijos anuales y porcentaje de costes variables. El margen de contribucion debe ser positivo.';
        el('capacity-note').textContent = result?.capacityExceeded ? 'El punto de equilibrio supera la capacidad indicada.' : 'Umbral operativo: no incluye inversion inicial, impuestos ni costes no incorporados a los parametros.';
        const chart = el('breakeven-chart');
        if (!result || result.exactMembers == null || !ticket || ticket <= 0) {
            chart.setAttribute('viewBox', '0 0 820 260');
            chart.innerHTML = '<text class="empty" x="410" y="130">Introduce costes, porcentaje variable y cuota anual para ver el punto de equilibrio.</text>';
            return;
        }
        const width = 820, height = 260;
        const left = 64, right = 790, top = 18, bottom = 205;
        const maxMembers = Math.max(capacity || 0, result.exactMembers * 1.2, 1);
        const maxValue = Math.max(
            maxMembers * ticket,
            fixed + maxMembers * ticket * (variable / 100),
            fixed,
        ) * 1.12;
        const x = members => left + members / maxMembers * (right - left);
        const y = value => bottom - value / maxValue * (bottom - top);
        const breakX = x(result.exactMembers);
        const breakY = y(result.revenue);
        const capacityMarkup = capacity != null && capacity >= 0
            ? `<line class="capacity-line" x1="${x(capacity)}" y1="${top}" x2="${x(capacity)}" y2="${bottom}"/><text x="${Math.min(x(capacity) + 5, right - 90)}" y="${top + 14}">Capacidad ${fmt(capacity)}</text>`
            : '';
        chart.setAttribute('viewBox', `0 0 ${width} ${height}`);
        chart.setAttribute(
            'aria-label',
            `Facturación y costes anuales por abonados. Punto de equilibrio: ${fmt(result.exactMembers)} abonados y ${money(result.revenue)}.`,
        );
        chart.innerHTML = `
            <line class="axis" x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}"/>
            <line class="axis" x1="${left}" y1="${top}" x2="${left}" y2="${bottom}"/>
            <text x="${left}" y="${top - 4}">${money(maxValue)}</text>
            <text x="${left}" y="${bottom}">0</text>
            <text x="${right}" y="${bottom + 18}" text-anchor="end">${fmt(maxMembers)} abonados</text>
            <text x="${left}" y="${top + 14}">EUR/año</text>
            <path class="revenue-line" d="M ${left} ${bottom} L ${right} ${y(maxMembers * ticket)}"/>
            <path class="cost-line" d="M ${left} ${y(fixed)} L ${right} ${y(fixed + maxMembers * ticket * (variable / 100))}"/>
            <line class="break-even-line" x1="${breakX}" y1="${top}" x2="${breakX}" y2="${bottom}"/>
            ${capacityMarkup}
            <circle cx="${breakX}" cy="${breakY}" r="5" fill="#a66a00"/>
            <text x="${Math.min(breakX + 8, right - 145)}" y="${Math.max(breakY - 9, top + 12)}">Equilibrio: ${fmt(result.exactMembers)} · ${money(result.revenue)}</text>
            <line class="revenue-line" x1="${left}" y1="238" x2="${left + 24}" y2="238"/>
            <text class="legend" x="${left + 30}" y="242">Facturación</text>
            <line class="cost-line" x1="${left + 150}" y1="238" x2="${left + 174}" y2="238"/>
            <text class="legend" x="${left + 180}" y="242">Costes totales</text>
            <line class="break-even-line" x1="${left + 310}" y1="238" x2="${left + 334}" y2="238"/>
            <text class="legend" x="${left + 340}" y="242">Punto de equilibrio</text>
            ${capacityMarkup ? '<line class="capacity-line" x1="600" y1="238" x2="624" y2="238"/><text class="legend" x="630" y="242">Capacidad</text>' : ''}
        `;
    }
    for (const id of ['fixed-cost', 'variable-cost', 'finance-ticket', 'capacity']) el(id).addEventListener('input', updateFinance);
    updateFinance();

    const simulation = DATA.simulation;

    el('simulation-controls').hidden = !simulation;
    el('simulation-empty').hidden = !!simulation;
    el('reset-scenario').disabled = !simulation;

    if (simulation) {
        function resetSimulation() {
            setValue('weight-demand', 1);
            setValue('weight-income', 1);
            setValue('weight-growth', 1);

            updateSimulation();
        }

        function updateSimulation() {
            const weights = {
                population: readNumber('weight-demand'),
                income: readNumber('weight-income'),
                growth: readNumber('weight-growth'),
            };

            el('weight-demand-value').textContent =
                fmt(weights.population, 1);

            el('weight-income-value').textContent =
                fmt(weights.income, 1);

            el('weight-growth-value').textContent =
                fmt(weights.growth, 1);

            const result = marketAnalysis.simulate(
                DATA,
                {weights}
            );

            if (result.error) {
                el('scenario-message').textContent = result.error;
                el('scenario-candidate-count').textContent = 'n/d';
                el('scenario-total').textContent = 'n/d';
                el('scenario-rows').innerHTML = '';
                return;
            }

            el('scenario-candidate-count').textContent =
                fmt(result.candidateCount);

            el('scenario-total').textContent =
                money(result.selectionTotal);

            el('scenario-message').textContent =
                `${result.excluded} municipios excluidos por falta de ` +
                `población, renta o crecimiento. ` +
                `${result.candidateCount} municipios presentan una presión ` +
                `competitiva inferior a la media de su cluster.`;

            el('scenario-rows').innerHTML = result.selection.length
                ? result.selection
                    .map((row, index) => `
                        <tr>
                            <td>${index + 1}</td>

                            <td class="name">
                                ${escapeHtml(row.name)}
                            </td>

                            <td>
                                ${fmt(row.scenarioCluster)}
                            </td>

                            <td>
                                ${fmt(row.competitionRate, 2)}
                            </td>

                            <td>
                                ${fmt(row.clusterMean, 2)}
                            </td>

                            <td>
                                ${money(row.annual_revenue_eur)}
                            </td>
                        </tr>
                    `)
                    .join('')
                : `
                    <tr>
                        <td colspan="6" class="empty">
                            No hay municipios seleccionables con estos pesos.
                        </td>
                    </tr>
                `;
        }

        for (const id of [
            'weight-demand',
            'weight-income',
            'weight-growth',
        ]) {
            el(id).addEventListener('input', updateSimulation);
        }

        el('reset-scenario').addEventListener(
            'click',
            resetSimulation
        );

        resetSimulation();
    }

    const sections = DATA.census_sections?.features || [], isochrones = DATA.isochrones?.features || [];
    const hasSpatial = sections.length + isochrones.length > 0;
    el('spatial-empty').hidden = hasSpatial;el('spatial-map').hidden = !hasSpatial;
    const cityIds = [...new Set([...sections, ...isochrones].map(feature => feature.properties.municipality_id))];
    for (const identity of cityIds) {const option = document.createElement('option');option.value = identity;option.textContent = byId.get(identity).name;el('spatial-city').append(option);}
    for (const minutes of [...new Set(isochrones.map(feature => feature.properties.minutes))].sort((left, right) => left - right)) {const option = document.createElement('option');option.value = String(minutes);option.textContent = minutes + ' min';el('travel-minutes').append(option);}
    el('spatial-city').disabled = !hasSpatial;el('show-sections').disabled = !sections.length;el('show-isochrones').disabled = !isochrones.length;
    el('travel-minutes').disabled = !isochrones.length;el('travel-mode').disabled = !isochrones.length;
    if (hasSpatial && window.L) {
        const spatialMap = L.map('spatial-map', {preferCanvas: true, fadeAnimation: false, zoomAnimation: false, scrollWheelZoom: false}).setView([37.3, -4.5], 7);
        L.tileLayer('https://www.ign.es/wmts/ign-base?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=IGNBase-gris&STYLE=default&FORMAT=image/jpeg&TILEMATRIXSET=GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}', {attribution: '© IGN', maxZoom: 18}).addTo(spatialMap);
        const layer = L.featureGroup().addTo(spatialMap);
        function refreshSpatial() {
            layer.clearLayers();const city = el('spatial-city').value, mode = el('travel-mode').value, minutes = el('travel-minutes').value;
            const filteredSections = el('show-sections').checked ? sections.filter(feature => city === 'all' || feature.properties.municipality_id === city) : [];
            const filteredIsochrones = el('show-isochrones').checked ? isochrones.filter(feature => (city === 'all' || feature.properties.municipality_id === city) && (mode === 'all' || feature.properties.mode === mode) && (minutes === 'all' || String(feature.properties.minutes) === minutes)) : [];
            for (const [features, type] of [[filteredSections, 'section'], [filteredIsochrones, 'isochrone']]) L.geoJSON({type: 'FeatureCollection', features}, {
                style: feature => ({color: type === 'section' ? '#2976ad' : '#007d69', weight: type === 'section' ? .8 : 1.5, fillOpacity: type === 'section' ? .12 : .08, dashArray: type === 'section' ? null : '5 3'}),
                onEachFeature: (feature, featureLayer) => {const props = feature.properties, content = document.createElement('div');const name = document.createElement('strong');name.textContent = type === 'section' ? props.name : props.minutes + ' min · ' + {drive: 'Coche', walk: 'A pie', bike: 'Bicicleta'}[props.mode];content.append(name);const detail = document.createElement('div');detail.textContent = type === 'section' ? fmt(props.target_population) + ' personas objetivo · ' + fmt(props.competitor_count) + ' competidores' : byId.get(props.municipality_id).name;const source = document.createElement('div');source.textContent = props.source;content.append(detail, source);featureLayer.bindPopup(content);}
            }).addTo(layer);
            el('spatial-status').textContent = `${filteredSections.length} secciones censales · ${filteredIsochrones.length} isocronas. Poligonos y tiempos aportados por el analisis territorial.`;
            el('section-rows').innerHTML = filteredSections.map(feature => {const props = feature.properties;return `<tr><td>${escapeHtml(props.name)}</td><td class="name">${escapeHtml(byId.get(props.municipality_id).name)}</td><td>${fmt(props.target_population)}</td><td>${money(props.income_eur)}</td><td>${fmt(props.competitor_count)}</td></tr>`;}).join('');
            if (layer.getLayers().some(item => item.getBounds().isValid())) spatialMap.fitBounds(layer.getBounds(), {padding: [20, 20], animate: false, maxZoom: 15});
        }
        for (const id of ['spatial-city', 'show-sections', 'show-isochrones', 'travel-mode', 'travel-minutes']) el(id).addEventListener('change', refreshSpatial);
        window.expansionMap = spatialMap;window.refreshSpatial = refreshSpatial;refreshSpatial();
    } else if (hasSpatial) {el('spatial-map').textContent = 'Mapa no disponible.';}
}