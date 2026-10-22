window.renderGoldDashboard = function (data) {
    const el = id => document.getElementById(id);
    const fmt = (value, digits = 0) => typeof value !== 'number' || !Number.isFinite(value)
        ? 'n/d'
        : new Intl.NumberFormat('es-ES', {maximumFractionDigits: digits}).format(value);
    const money = value => value == null ? 'n/d' : `${fmt(value)} EUR`;
    const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
    const rows = data.municipalities;
    const byId = new Map(rows.map(row => [row.id, row]));
    const selected = data.selection.map(id => byId.get(id)).filter(Boolean);
    const baseline = data.baseline.map(id => byId.get(id)).filter(Boolean);
    const sum = (list, key) => list.length && list.every(row => row[key] != null)
        ? list.reduce((total, row) => total + row[key], 0)
        : null;
    const totalRevenue = sum(selected, 'annual_revenue_eur');
    const scenarioLabel = `Escenario ${data.scenario} · ${data.revenue_rule === 'C' ? 'cuota por atractivo' : 'demanda no cubierta'}`;

    document.title = data.metadata.title;
    el('title').textContent = data.metadata.title;
    el('region').textContent = `${data.metadata.region} / Expansión de mercado`;
    el('period').textContent = data.metadata.period;
    el('target-description').textContent = data.metadata.target_description;
    el('baseline-description').textContent = data.metadata.baseline_description;
    el('methodology').textContent = data.metadata.methodology;
    el('revenue-method').textContent = data.metadata.revenue_method;
    const list = (id, values, empty) => {
        el(id).replaceChildren();
        for (const value of values.length ? values : [empty]) {
            const item = document.createElement('li');
            item.textContent = value;
            el(id).append(item);
        }
    };
    list('assumptions', data.metadata.assumptions, 'Sin supuestos documentados.');
    list('limitations', data.metadata.limitations, 'Sin limitaciones documentadas.');
    el('sources').textContent = data.metadata.sources.map(source => source.label).join(' · ');

    const decisionStats = document.querySelector('#decision .stats');
    decisionStats.children[0].querySelector('strong').textContent = `${selected.length} municipios`;
    decisionStats.children[0].querySelector('span').textContent = data.clusters_available
        ? 'Candidatas viables del modelo'
        : 'Municipios viables con mayor facturación estimada';
    el('total-revenue').textContent = money(totalRevenue);
    el('candidate-count').textContent = data.clusters_available
        ? fmt(rows.filter(row => row.candidate).length)
        : 'n/d';
    document.querySelector('#decision .stats > div:last-child span').textContent =
        data.clusters_available ? 'Municipios candidatos' : 'Candidatos del estudio no disponibles';

    const mapTitle = document.querySelector('#decision .map-shell h2');
    mapTitle.textContent = 'Cobertura geográfica';
    const map = el('map');
    map.setAttribute('aria-label', 'Coordenadas no incluidas en Gold');
    map.textContent = 'Gold no contiene coordenadas municipales; no se representa un mapa.';
    map.style.display = 'grid';
    map.style.placeItems = 'center';
    map.style.padding = '24px';
    map.style.color = 'var(--muted)';
    el('selected-rows').closest('section').querySelector('h2').textContent =
        data.clusters_available ? 'Selección del modelo de negocio' : 'Municipios viables destacados';
    document.querySelector('#selected-rows').closest('table').querySelector('thead').innerHTML =
        '<tr><th>#</th><th class="name">Municipio</th><th>Score</th><th>Demanda /<br>competidor</th><th>Facturación<br>anual estimada</th><th class="name">Lectura</th></tr>';
    el('selected-rows').innerHTML = selected.map((row, index) =>
        `<tr><td>${index + 1}</td><td class="name">${escape(row.name)}<small>${escape(row.province)}</small></td><td>${fmt(row.score, 1)}</td><td>${fmt(row.demand_per_competitor)}</td><td class="money">${money(row.annual_revenue_eur)}</td><td class="reason">${escape(row.reason)}</td></tr>`
    ).join('') || '<tr><td colspan="6" class="empty">No hay municipios viables en este escenario.</td></tr>';
    el('selection-note').textContent = `${scenarioLabel}. Las estimaciones son escenarios, no predicciones ni recomendaciones de inversión.`;

    el('baseline-rows').innerHTML = baseline.map((row, index) =>
        `<tr><td>${index + 1} · ${escape(row.name)}</td><td>${fmt(row.demand_per_competitor)}</td><td class="money">${money(row.annual_revenue_eur)}</td></tr>`
    ).join('');
    const comparison = [
        ['Selección', selected],
        ['Baseline', baseline]
    ];
    el('comparison-rows').innerHTML = comparison.map(([label, listing]) => {
        const demand = listing.map(row => row.demand_per_competitor).filter(value => value != null);
        const meanDemand = demand.length ? demand.reduce((total, value) => total + value, 0) / demand.length : null;
        return `<tr><td>${label}</td><td>${fmt(meanDemand)}<small>${demand.length}/${listing.length} calculables</small></td><td class="money">${money(sum(listing, 'annual_revenue_eur'))}</td></tr>`;
    }).join('');
    const selectedIds = new Set(data.selection);
    const baselineIds = new Set(data.baseline);
    const entrants = selected.filter(row => !baselineIds.has(row.id)).map(row => row.name);
    const exits = baseline.filter(row => !selectedIds.has(row.id)).map(row => row.name);
    el('changes').textContent = `Entran: ${entrants.join(', ') || 'ninguno'}. Salen: ${exits.join(', ') || 'ninguno'}.`;
    document.querySelector('#decision .comparison > .caption').textContent =
        'Los totales suman los escenarios de facturación por municipio; no son ventas observadas.';

    const decisionSections = document.querySelectorAll('#decision > .analysis-band');
    decisionSections[0].querySelector('h2').textContent = 'Punto de equilibrio operativo';
    decisionSections[0].querySelector('.formula-note').textContent =
        'Gold no incluye los costes fijos y variables necesarios para calcular el punto de equilibrio.';
    for (const input of decisionSections[0].querySelectorAll('input')) input.disabled = true;
    el('capacity-note').textContent = 'Sin datos de costes, cuota y capacidad en Gold; no se calcula un umbral.';
    decisionSections[1].querySelector('h2').textContent = 'Limitaciones de mercado';
    const questions = decisionSections[1].querySelectorAll('.question');
    questions[0].querySelector('summary').textContent = '¿El recuento de instalaciones confirma la competencia real?';
    el('competition-answer').textContent =
        'No. Gold agrega instalaciones de OpenStreetMap; el recuento no permite confirmar ausencias ni sustituye una auditoría de mercado.';
    el('market-checks').replaceChildren();
    questions[1].hidden = true;
    questions[2].querySelector('summary').textContent = '¿Cómo se interpreta la selección?';
    el('selection-answer').textContent = data.clusters_available
        ? 'Se muestran candidatos viables del modelo de negocio con los clusters disponibles. El resultado depende de los supuestos elegidos.'
        : 'No hay clusters cargados. Se muestran municipios viables ordenados por facturación estimada, junto con un baseline por población objetivo.';

    el('municipal-count').textContent = fmt(rows.length);
    el('target-count').textContent = fmt(rows.reduce((total, row) => total + row.target_population, 0));
    el('competition-count').textContent = fmt(rows.reduce((total, row) => total + row.competitor_count, 0));
    const municipalRows = [...rows].sort((left, right) => left.name.localeCompare(right.name, 'es'));
    const municipalHeaders = el('municipal-rows').closest('table').querySelectorAll('thead th');
    municipalHeaders[5].textContent = 'Instalaciones OSM';
    municipalHeaders[6].textContent = 'Instalaciones ponderadas / 10.000 objetivo';
    el('municipal-rows').innerHTML = municipalRows.map(row =>
        `<tr><td>${escape(row.name)}<small>${escape(row.province)}</small></td><td>${fmt(row.target_population)}</td><td>${fmt(row.growth_pct, 1)}</td><td>${money(row.income_eur)}</td><td>n/d</td><td>${fmt(row.competitor_count)}<small>${escape(row.coverage_note)}</small></td><td>${fmt(row.target_population ? row.competitors_weighted / row.target_population * 10000 : null, 2)}</td></tr>`
    ).join('');

    const groupsKey = data.clusters_available ? 'cluster' : 'province';
    const groups = new Map();
    for (const row of rows) {
        if (!groups.has(row[groupsKey])) groups.set(row[groupsKey], []);
        groups.get(row[groupsKey]).push(row);
    }
    const summaries = [...groups].map(([name, members]) => {
        const ratios = members
            .filter(row => row.target_population > 0)
            .map(row => row.competitors_weighted / row.target_population * 10000);
        return {
            name,
            value: ratios.length ? ratios.reduce((total, value) => total + value, 0) / ratios.length : null
        };
    });
    const maxValue = Math.max(...summaries.map(group => group.value ?? 0), 1);
    document.querySelector('#intelligence .intelligence section:nth-child(2) h2').textContent =
        data.clusters_available ? 'Oferta por cluster' : 'Oferta por provincia';
    document.querySelector('#intelligence .intelligence section:nth-child(2) .caption').textContent =
        'Instalaciones ponderadas por 10.000 personas objetivo · media municipal';
    el('groups').innerHTML = summaries.map(group =>
        `<div class="group"><span class="group-label">${escape(group.name)}</span><div class="track"><span style="width:${(group.value ?? 0) / maxValue * 100}%"></span></div><strong>${fmt(group.value, 2)}</strong></div>`
    ).join('');
    el('group-note').textContent = 'Los recuentos incluyen gimnasios y otras instalaciones deportivas según Gold.';

    el('audit-summary').textContent = 'Gold no contiene una auditoría manual de competidores.';
    el('audit-rows').innerHTML = '<tr><td colspan="4" class="empty">Sin registros de auditoría en la fuente.</td></tr>';
    document.querySelector('#intelligence .audit .icon').hidden = true;
    el('competition-answer').textContent += ' No hay comprobaciones de mercado auditadas en Gold.';
    el('spatial-empty').textContent =
        'Gold no contiene secciones censales, isocronas ni coordenadas municipales.';
    el('spatial-city').disabled = true;
    el('travel-mode').disabled = true;
    el('travel-minutes').disabled = true;
    el('show-sections').disabled = true;
    el('show-isochrones').disabled = true;
    el('section-rows').innerHTML =
        '<tr><td colspan="5" class="empty">No aportado en la tabla Gold.</td></tr>';
    el('simulation-empty').textContent =
        'La simulación interactiva del estudio no está disponible en Gold.';
    document.querySelector('#intelligence .analysis-band').hidden = true;

    const municipalDownload = el('municipal-download');
    const csvRows = municipalRows.map(row => ({
        municipality_code: row.id,
        municipality_name: row.name,
        province: row.province,
        population_18_50: row.target_population,
        population_growth_pct: row.growth_pct,
        mean_net_income_per_person: row.income_eur,
        gyms_count: row.gyms_count,
        other_sports_facilities_count: row.other_sports_facilities_count,
        weighted_competitors: row.competitors_weighted,
        annual_revenue_scenario_eur: row.annual_revenue_eur
    }));
    const csvCell = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
    municipalDownload.href = URL.createObjectURL(new Blob([
        '\uFEFF' + [
            Object.keys(csvRows[0] ?? {}).map(csvCell).join(','),
            ...csvRows.map(row => Object.values(row).map(csvCell).join(','))
        ].join('\r\n')
    ], {type: 'text/csv;charset=utf-8'}));
    el('audit-download').hidden = true;
    const jsonLink = el('data-download');
    jsonLink.download = 'gold-study-view.json';
    jsonLink.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));

    const tabs = [...document.querySelectorAll('[role=tab]')];
    const showTab = tab => {
        for (const item of tabs) {
            const active = item === tab;
            item.setAttribute('aria-selected', String(active));
            item.tabIndex = active ? 0 : -1;
            el(item.getAttribute('aria-controls')).hidden = !active;
        }
    };
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => showTab(tab));
        tab.addEventListener('keydown', event => {
            const next = event.key === 'ArrowRight' ? tabs[(index + 1) % tabs.length]
                : event.key === 'ArrowLeft' ? tabs[(index + tabs.length - 1) % tabs.length]
                    : event.key === 'Home' ? tabs[0]
                        : event.key === 'End' ? tabs[tabs.length - 1] : null;
            if (next) {
                event.preventDefault();
                showTab(next);
                next.focus();
            }
        });
    });
    showTab(el('tab-situation'));
    if (window.lucide) window.lucide.createIcons();
};
