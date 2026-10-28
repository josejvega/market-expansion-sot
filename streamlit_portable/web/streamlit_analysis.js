const marketAnalysis = {
    breakEven(fixed, variableRatio, ticket, capacity = null) {
        if (![fixed, variableRatio].every(value => typeof value === 'number' && Number.isFinite(value)) || fixed < 0 || variableRatio < 0 || variableRatio >= 1) return null;
        const revenue = fixed / (1 - variableRatio);
        const members = typeof ticket === 'number' && ticket > 0 ? Math.ceil(revenue / ticket) : null;
        return {revenue, members, exactMembers: members == null ? null : revenue / ticket, capacityExceeded: members != null && capacity != null && members > capacity};
    },
simulate(study, settings) {
    const {
        penetration,
        monthlyTicket,
        maximumMarketShare,
        attractiveness,
        annualCost
    } = settings;

    if (
        !Number.isFinite(penetration) ||
        !Number.isFinite(monthlyTicket) ||
        !Number.isFinite(maximumMarketShare) ||
        !Number.isFinite(attractiveness) ||
        !Number.isFinite(annualCost)
    ) {
        return {
            error: 'Los parámetros económicos no son válidos.'
        };
    }

    if (
        penetration < 0 ||
        penetration > 1 ||
        monthlyTicket < 0 ||
        maximumMarketShare < 0 ||
        maximumMarketShare > 1 ||
        attractiveness <= 0 ||
        annualCost < 0
    ) {
        return {
            error: 'Los parámetros económicos están fuera de rango.'
        };
    }

    /*
     * El clustering ya está hecho.
     * El simulador económico trabaja únicamente
     * con municipios candidatos del modelo.
     */
    const candidates = study.municipalities
        .filter(row => row.candidate)
        .map(row => {
            const competition =
                Number(row.competitors_weighted);

            const targetPopulation =
                Number(row.target_population);

            if (
                !Number.isFinite(competition) ||
                !Number.isFinite(targetPopulation) ||
                targetPopulation <= 0
            ) {
                return null;
            }

            /*
             * 1. Demanda potencial
             */
            const potentialDemand =
                targetPopulation * penetration;

            /*
             * 2. Cuota capturable
             */
            const capturedShare =
                Math.min(
                    attractiveness /
                        (competition + attractiveness),
                    maximumMarketShare
                );

            /*
             * 3. Socios potenciales
             *
             * NO se aplica:
             *
             * Math.min(potentialMembers, 2600)
             */
            const potentialMembers =
                potentialDemand * capturedShare;

            /*
             * 4. Facturación potencial anual
             */
            const scenarioRevenue =
                potentialMembers *
                monthlyTicket *
                12;

            /*
             * 5. Margen potencial anual
             */
            const scenarioMargin =
                scenarioRevenue - annualCost;

            return {
                ...row,
                potentialDemand,
                capturedShare,
                potentialMembers,
                scenarioRevenue,
                scenarioMargin,
                scenarioViable:
                    scenarioMargin >= 0
            };
        })
        .filter(Boolean);

    /*
     * Ordenamos por facturación potencial.
     */
    const selection = [...candidates]
        .sort(
            (left, right) =>
                right.scenarioRevenue -
                    left.scenarioRevenue ||
                String(left.id).localeCompare(
                    String(right.id)
                )
        )
        .slice(0, 5);

    const selectionTotal =
        selection.length
            ? selection.reduce(
                (total, row) =>
                    total + row.scenarioRevenue,
                0
            )
            : null;

    const marginTotal =
        selection.length
            ? selection.reduce(
                (total, row) =>
                    total + row.scenarioMargin,
                0
            )
            : null;

    return {
        selection,
        selectionTotal,
        marginTotal,
        candidates: candidates.length
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

/*
 * CALCULADORA 1
 * Rentabilidad manual de un centro:
 * socios inscritos × ticket mensual × 12 − coste anual
 */

setValue(
    'finance-members',
    2071
);

setValue(
    'finance-ticket',
    finance.monthly_ticket_eur ??
        (
            finance.annual_ticket_eur != null
                ? finance.annual_ticket_eur / 12
                : 22.37
        )
);

setValue(
    'fixed-cost',
    finance.annual_cost_eur ??
        finance.annual_fixed_cost_eur ??
        556000
);

function updateFinance() {
    const members =
        readNumber('finance-members');

    const monthlyTicket =
        readNumber('finance-ticket');

    const annualCost =
        readNumber('fixed-cost');

    const valid =
        Number.isFinite(members) &&
        Number.isFinite(monthlyTicket) &&
        Number.isFinite(annualCost) &&
        members >= 0 &&
        monthlyTicket >= 0 &&
        annualCost >= 0;

    if (!valid) {
        el('breakeven-revenue').textContent =
            'n/d';

        el('breakeven-members').textContent =
            'n/d';

        el('profitability-answer').textContent =
            'Introduce socios, ticket mensual y coste anual válidos.';

        el('capacity-note').textContent =
            '';

        const chart =
            el('breakeven-chart');

        if (chart) {
            chart.innerHTML = '';
            chart.hidden = true;
        }

        return;
    }

    const revenue =
        members * monthlyTicket * 12;

    const margin =
        revenue - annualCost;

    el('breakeven-revenue').textContent =
        money(revenue);

    el('breakeven-members').textContent =
        money(margin);

    el('profitability-answer').textContent =
        margin >= 0
            ? `Centro viable: margen operativo de ${money(margin)}.`
            : `Centro no viable: margen operativo de ${money(margin)}.`;

    el('capacity-note').textContent =
        `${fmt(members)} socios × ` +
        `${fmt(monthlyTicket, 2)} EUR/mes × 12 = ` +
        `${money(revenue)} de facturación anual.`;

    const chart =
        el('breakeven-chart');

    if (chart) {
        chart.innerHTML = '';
        chart.hidden = true;
    }
}

for (const id of [
    'finance-members',
    'finance-ticket',
    'fixed-cost'
]) {
    el(id).addEventListener(
        'input',
        updateFinance
    );
}

updateFinance();

const simulation = DATA.simulation;

el('reset-scenario').disabled = !simulation;

if (simulation) {

    function resetSimulation() {
        setValue(
            'penetration',
            simulation.penetration * 100
        );

        setValue(
            'monthly-ticket',
            simulation.monthly_ticket_eur
        );

        setValue(
            'maximum-share',
            simulation.maximum_market_share * 100
        );

        setValue(
            'attractiveness',
            simulation.attractiveness
        );

        setValue(
            'annual-cost',
            simulation.annual_cost_eur
        );

        updateSimulation();
    }


    function updateSimulation() {
        const penetration =
            readNumber('penetration');

        const monthlyTicket =
            readNumber('monthly-ticket');

        const maximumMarketShare =
            readNumber('maximum-share');

        const attractiveness =
            readNumber('attractiveness');

        const annualCost =
            readNumber('annual-cost');


        /*
         * Actualizar etiquetas de los sliders
         */
        el('penetration-value').textContent =
            penetration == null
                ? 'n/d'
                : fmt(penetration, 1) + ' %';

        el('monthly-ticket-value').textContent =
            monthlyTicket == null
                ? 'n/d'
                : fmt(monthlyTicket, 2) + ' €';

        el('maximum-share-value').textContent =
            maximumMarketShare == null
                ? 'n/d'
                : fmt(maximumMarketShare, 0) + ' %';

        el('attractiveness-value').textContent =
            attractiveness == null
                ? 'n/d'
                : fmt(attractiveness, 2);

        el('annual-cost-value').textContent =
            annualCost == null
                ? 'n/d'
                : money(annualCost);


        /*
         * Ejecutar escenario económico
         */
        const result =
            marketAnalysis.simulate(
                DATA,
                {
                    penetration:
                        penetration == null
                            ? NaN
                            : penetration / 100,

                    monthlyTicket:
                        monthlyTicket == null
                            ? NaN
                            : monthlyTicket,

                    maximumMarketShare:
                        maximumMarketShare == null
                            ? NaN
                            : maximumMarketShare / 100,

                    attractiveness:
                        attractiveness == null
                            ? NaN
                            : attractiveness,

                    annualCost:
                        annualCost == null
                            ? NaN
                            : annualCost
                }
            );


        /*
         * Error
         */
        if (result.error) {
            el('scenario-total').textContent =
                'n/d';

            el('scenario-margin').textContent =
                'n/d';

            el('scenario-message').textContent =
                result.error;

            el('scenario-rows').innerHTML =
                '';

            return;
        }


        /*
         * KPIs
         */
        el('scenario-total').textContent =
            money(result.selectionTotal);

        el('scenario-margin').textContent =
            money(result.marginTotal);

        el('scenario-message').textContent =
            `${result.candidates} municipios candidatos evaluados. ` +
            `La simulación calcula potencial económico sin aplicar ` +
            `el límite de 2.600 socios por centro.`;


        /*
         * Top 5
         */
        el('scenario-rows').innerHTML =
            result.selection.length
                ? result.selection
                    .map(
                        (row, index) => `
                            <tr>

                                <td>
                                    ${index + 1}
                                </td>

                                <td class="name">
                                    ${escapeHtml(row.name)}
                                </td>

                                <td>
                                    ${fmt(row.potentialMembers)}
                                </td>

                                <td>
                                    ${fmt(
                                        row.capturedShare * 100,
                                        1
                                    )} %
                                </td>

                                <td>
                                    ${money(
                                        row.scenarioRevenue
                                    )}
                                </td>

                                <td>
                                    ${money(
                                        row.scenarioMargin
                                    )}
                                    <small>
                                        ${
                                            row.scenarioViable
                                                ? 'Margen positivo'
                                                : 'Margen negativo'
                                        }
                                    </small>
                                </td>

                            </tr>
                        `
                    )
                    .join('')
                : `
                    <tr>
                        <td
                          colspan="6"
                          class="empty">
                            No hay candidatos calculables.
                        </td>
                    </tr>
                `;
    }


    /*
     * Eventos
     */
    for (const id of [
        'penetration',
        'monthly-ticket',
        'maximum-share',
        'attractiveness',
        'annual-cost'
    ]) {
        el(id).addEventListener(
            'input',
            updateSimulation
        );
    }


    el('reset-scenario').addEventListener(
        'click',
        resetSimulation
    );


    /*
     * Estado inicial = escenario central
     */
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