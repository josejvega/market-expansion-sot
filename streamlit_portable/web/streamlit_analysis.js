const marketAnalysis = {
    breakEven(fixed, variableRatio, ticket, capacity = null) {
        if (![fixed, variableRatio].every(value => typeof value === 'number' && Number.isFinite(value)) || fixed < 0 || variableRatio < 0 || variableRatio >= 1) return null;
        const revenue = fixed / (1 - variableRatio);
        const members = typeof ticket === 'number' && ticket > 0 ? Math.ceil(revenue / ticket) : null;
        return {revenue, members, capacityExceeded: members != null && capacity != null && members > capacity};
    },
    simulate(study, settings) {
        const weights = settings.weights;
        if (Object.values(weights).some(value => !Number.isFinite(value) || value < 0)) return {error: 'Los pesos deben ser numeros no negativos.'};
        const totalWeight = Object.values(weights).reduce((total, value) => total + value, 0);
        if (!Number.isFinite(totalWeight) || totalWeight <= 0) return {error: 'Al menos un peso debe ser mayor que cero.'};
        if (![settings.penetration, settings.ticket, settings.multiplier].every(value => Number.isFinite(value) && value >= 0) || settings.penetration > 1) return {error: 'Parametros de escenario fuera de rango.'};
        const profiles = study.simulation?.target_profiles || [];
        const profile = profiles.find(item => item.id === settings.profile);
        if (settings.profile !== 'current' && !profile) return {error: 'Perfil de publico no disponible.'};
        const rows = study.municipalities.map(row => {
            const target = (profile ? profile.populations[row.id] : row.target_population) * settings.multiplier;
            const members = row.competitor_count == null ? null : target * settings.penetration / (row.competitor_count + 1);
            return {...row, scenarioTarget: target, scenarioMembers: members, scenarioRevenue: members == null ? null : members * settings.ticket,
                criteria: {demand: target, income: row.income_eur, growth: row.growth_pct}};
        });
        const usable = rows.filter(row => row.scenarioTarget > 0 && Object.entries(weights).every(([key, weight]) => weight === 0 || row.criteria[key] != null));
        const ranges = {};
        for (const key of Object.keys(weights)) {
            const values = usable.map(row => row.criteria[key]).filter(value => value != null);
            ranges[key] = values.length ? [Math.min(...values), Math.max(...values)] : [0, 0];
        }
        for (const row of usable) row.scenarioScore = Object.entries(weights).reduce((total, [key, weight]) => {
            if (!weight) return total;
            const [low, high] = ranges[key];
            return total + weight / totalWeight * (high === low ? .5 : (row.criteria[key] - low) / (high - low)) * 100;
        }, 0);
        const order = (left, right) => right.scenarioScore - left.scenarioScore || right.scenarioTarget - left.scenarioTarget || left.id.localeCompare(right.id);
        const selection = usable.filter(row => row.candidate).sort(order).slice(0, 5);
        const baseline = [...usable].sort((left, right) => right.scenarioTarget - left.scenarioTarget || left.id.localeCompare(right.id)).slice(0, 5);
        const total = listing => listing.length !== 5 || listing.some(row => row.scenarioRevenue == null) ? null : listing.reduce((sum, row) => sum + row.scenarioRevenue, 0);
        return {selection, baseline, selectionTotal: total(selection), baselineTotal: total(baseline), excluded: rows.length - usable.length};
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
    setValue('variable-cost', finance.variable_cost_ratio == null ? 5 : finance.variable_cost_ratio * 100);
    setValue('finance-ticket', finance.annual_ticket_eur);
    setValue('capacity', finance.capacity_members);
    el('finance-data-note').textContent = [
        `Referencias del escenario central: costes fijos ${money(finance.annual_fixed_cost_eur)}, cuota anual ${money(finance.annual_ticket_eur)} y capacidad ${fmt(finance.capacity_members)} abonados.`,
        finance.variable_cost_ratio == null
            ? 'No hay un porcentaje de costes variables documentado para el proyecto. Se muestra 5% solo como ejemplo editable, no como dato real.'
            : 'El porcentaje de costes variables se ha cargado desde los supuestos del escenario.'
    ].join(' ');
    function renderBreakEvenChart(fixed, ticket, capacity, variablePercent) {
        const chart = el('break-even-chart');
        if (
            fixed == null || fixed < 0 || ticket == null || ticket <= 0
            || capacity == null || capacity <= 0
            || variablePercent == null || variablePercent < 0 || variablePercent >= 100
        ) {
            chart.replaceChildren();
            el('break-even-chart-note').textContent =
                'Introduce costes fijos, un porcentaje de costes variables entre 0% y 99,9%, una cuota anual positiva y la capacidad para ver el punto de equilibrio.';
            return;
        }

        const width = 760, height = 430, left = 82, right = 28, top = 52, bottom = 76;
        const plotWidth = width - left - right, plotHeight = height - top - bottom;
        const variableRatio = variablePercent / 100;
        const breakEvenMembers = fixed / (ticket * (1 - variableRatio));
        const maxMembers = Math.max(capacity, breakEvenMembers, 1) * 1.12;
        const maxRevenue = Math.max(maxMembers * ticket, fixed + maxMembers * ticket * variableRatio, 1) * 1.08;
        const x = members => left + members / maxMembers * plotWidth;
        const y = euros => top + plotHeight - euros / maxRevenue * plotHeight;
        const revenue = members => members * ticket;
        const variableCosts = members => revenue(members) * variableRatio;
        const totalCosts = members => fixed + variableCosts(members);
        const line = (valueAt, color, dash = '') => {
            const points = Array.from({length: 41}, (_, index) => {
                const members = maxMembers * index / 40;
                return `${x(members).toFixed(1)},${y(valueAt(members)).toFixed(1)}`;
            }).join(' ');
            return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ''}/>`;
        };
        const yTicks = [0, .25, .5, .75, 1].map(fraction => {
            const value = maxRevenue * fraction, position = y(value);
            return `<line x1="${left}" y1="${position}" x2="${width-right}" y2="${position}" stroke="#e5e1e8"/><text x="${left-9}" y="${position+4}" text-anchor="end" fill="#66616c" font-size="11">${money(value)}</text>`;
        }).join('');
        const xTicks = [0, .25, .5, .75, 1].map(fraction => {
            const value = maxMembers * fraction, position = x(value);
            return `<line x1="${position}" y1="${top+plotHeight}" x2="${position}" y2="${top+plotHeight+5}" stroke="#66616c"/><text x="${position}" y="${top+plotHeight+21}" text-anchor="middle" fill="#66616c" font-size="11">${fmt(value, 0)}</text>`;
        }).join('');
        const capacityX = x(capacity);
        const capacityLine = `<line x1="${capacityX}" y1="${top}" x2="${capacityX}" y2="${top+plotHeight}" stroke="#8a5900" stroke-width="2" stroke-dasharray="5 4"/><text x="${capacityX}" y="${top-10}" text-anchor="middle" fill="#8a5900" font-size="11">Capacidad ${fmt(capacity)}</text>`;
        const breakEvenX = x(breakEvenMembers), breakEvenY = y(revenue(breakEvenMembers));
        const labelX = breakEvenX > left + plotWidth * .7 ? breakEvenX - 8 : breakEvenX + 8;
        const labelAnchor = labelX < breakEvenX ? 'end' : 'start';
        const breakEvenMarker = `<line x1="${breakEvenX}" y1="${top}" x2="${breakEvenX}" y2="${top+plotHeight}" stroke="#17151b" stroke-dasharray="3 4"/><circle cx="${breakEvenX}" cy="${breakEvenY}" r="6" fill="#17151b" stroke="#fff" stroke-width="2"/><text x="${labelX}" y="${breakEvenY-12}" text-anchor="${labelAnchor}" fill="#17151b" font-size="11" font-weight="600">Equilibrio: ${fmt(Math.ceil(breakEvenMembers))} abonados</text>`;
        const legend = [
            ['#a100ff', 'Ingresos'],
            ['#8a5900', 'Costes fijos'],
            ['#2976ad', 'Costes variables'],
            ['#007d69', 'Costes totales']
        ].map(([color, label], index) => {
            const legendX = left + index * 162;
            return `<line x1="${legendX}" y1="24" x2="${legendX+18}" y2="24" stroke="${color}" stroke-width="3"/><text x="${legendX+24}" y="28" fill="#17151b" font-size="11">${label}</text>`;
        }).join('');
        chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Una gráfica de ingresos y costes anuales según abonados. Muestra costes fijos, variables, totales y el punto donde los ingresos igualan los costes totales, con la capacidad del centro.">${legend}${yTicks}${xTicks}<line x1="${left}" y1="${top+plotHeight}" x2="${width-right}" y2="${top+plotHeight}" stroke="#66616c"/>${capacityLine}${line(() => fixed, '#8a5900', '6 4')}${line(variableCosts, '#2976ad')}${line(totalCosts, '#007d69')}${line(revenue, '#a100ff')}${breakEvenMarker}<text x="${left+plotWidth/2}" y="${height-15}" text-anchor="middle" fill="#66616c" font-size="11">Abonados</text><text transform="translate(17 ${top+plotHeight/2}) rotate(-90)" text-anchor="middle" fill="#66616c" font-size="11">Euros al año</text></svg>`;
        const note = breakEvenMembers <= capacity
            ? `Con el ${fmt(variablePercent, 1)}% de costes variables, el cruce de ingresos y costes totales ocurre en ${fmt(Math.ceil(breakEvenMembers))} abonados, dentro de la capacidad de ${fmt(capacity)}.`
            : `Con el ${fmt(variablePercent, 1)}% de costes variables, el equilibrio requiere ${fmt(Math.ceil(breakEvenMembers))} abonados, por encima de la capacidad de ${fmt(capacity)}.`;
        el('break-even-chart-note').textContent = `${note} Los costes totales son costes fijos más costes variables; la línea vertical discontinua marca la capacidad.`;
    }
    function updateFinance() {
        const fixed = readNumber('fixed-cost'), variable = readNumber('variable-cost');
        const ticket = readNumber('finance-ticket'), capacity = readNumber('capacity');
        const result = marketAnalysis.breakEven(fixed, variable == null ? null : variable / 100, ticket, capacity);
        el('breakeven-revenue').textContent = result ? money(result.revenue) : 'n/d';
        el('breakeven-members').textContent = result ? fmt(result.members) : 'n/d';
        let explanation;
        if (fixed == null || variable == null) {
            explanation = 'Introduce los costes fijos anuales y el porcentaje de costes variables sobre ventas. Sin este último dato no se puede calcular la facturación mínima.';
        } else if (variable < 0 || variable >= 100) {
            explanation = 'El porcentaje de costes variables debe ser mayor o igual que 0% y menor que 100%.';
        } else if (result == null) {
            explanation = 'Revisa los valores introducidos: los costes fijos deben ser no negativos.';
        } else {
            explanation = `Con ${money(fixed)} de costes fijos y ${fmt(variable, 1)} % de costes variables, la facturación mínima estimada es ${money(result.revenue)} al año. `;
            explanation += ticket == null || ticket <= 0
                ? 'Introduce una cuota anual positiva para estimar los abonados necesarios.'
                : `Equivale a ${fmt(result.members)} abonados a la cuota indicada.`;
        }
        el('profitability-answer').textContent = explanation;
        el('profitability-answer-faq').textContent = explanation;
        el('capacity-note').textContent = result?.capacityExceeded ? 'El punto de equilibrio supera la capacidad indicada.' : 'Umbral operativo: no incluye inversión inicial, impuestos ni costes no incorporados a los parámetros.';
        renderBreakEvenChart(fixed, ticket, capacity, variable);
    }
    for (const id of ['fixed-cost', 'variable-cost', 'finance-ticket', 'capacity']) el(id).addEventListener('input', updateFinance);
    updateFinance();

    const simulation = DATA.simulation;
    el('simulation-controls').hidden = !simulation;
    el('simulation-empty').hidden = !!simulation;
    el('reset-scenario').disabled = !simulation;
    if (simulation) {
        for (const profile of simulation.target_profiles || []) {const option = document.createElement('option');option.value = profile.id;option.textContent = profile.label;el('target-profile').append(option);}
        function resetSimulation() {
            setValue('target-profile', 'current');setValue('target-scale', 100);setValue('penetration', simulation.penetration * 100);setValue('scenario-ticket', simulation.annual_ticket_eur);
            for (const key of ['demand', 'income', 'growth']) {el('weight-' + key).max = Math.max(100, simulation.weights[key]);el('weight-' + key).step = 'any';setValue('weight-' + key, simulation.weights[key]);}
            updateSimulation();
        }
        function updateSimulation() {
            const weights = Object.fromEntries(['demand', 'income', 'growth'].map(key => [key, readNumber('weight-' + key)]));
            el('target-scale-value').textContent = fmt(readNumber('target-scale')) + ' %';
            for (const [key, value] of Object.entries(weights)) el('weight-' + key + '-value').textContent = fmt(value, 2);
            const result = marketAnalysis.simulate(DATA, {profile: el('target-profile').value, multiplier: readNumber('target-scale') / 100, penetration: readNumber('penetration') == null ? NaN : readNumber('penetration') / 100, ticket: readNumber('scenario-ticket') ?? NaN, weights});
            el('scenario-message').textContent = result.error || (result.selection.length < 5 ? 'No hay cinco candidatas con datos suficientes para estos pesos.' : `${result.excluded} municipios excluidos por datos insuficientes o publico objetivo nulo. Seleccion dentro de las candidatas entregadas.`);
            el('scenario-total').textContent = money(result.selectionTotal);
            el('scenario-baseline').textContent = money(result.baselineTotal);
            el('scenario-rows').innerHTML = (result.selection || []).map((row, index) => `<tr><td>${index + 1}</td><td class="name">${escapeHtml(row.name)}</td><td>${fmt(row.scenarioScore, 1)}</td><td>${fmt(row.scenarioMembers)}</td><td>${money(row.scenarioRevenue)}</td></tr>`).join('');
            el('scenario-baseline-names').textContent = result.baseline ? 'Baseline del escenario: ' + result.baseline.map(row => row.name).join(', ') + '.' : '';
        }
        for (const control of el('simulation-controls').querySelectorAll('input,select')) control.addEventListener('input', updateSimulation);
        el('reset-scenario').addEventListener('click', resetSimulation);
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