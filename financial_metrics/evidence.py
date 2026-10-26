"""Render model-selected evidence without accepting model-supplied financial labels or values."""
from .policy import LABELS


def _warnings(result, row):
    return list(dict.fromkeys(result.get('warnings', []) + result.get('context', {}).get('warnings', []) + row.get('warnings', [])))


def fields_action(row):
    return [('usd', 'amount USD'), ('units', 'units of ' + row.get('ticker', 'the instrument')),
            ('avg_price_usd', 'average price USD'), ('m_at_action', 'net mNAV at action'),
            ('q_at_action', 'preferred price divided by liquidation preference at action'),
            ('coins_per_share_before', 'coins per diluted share before action'),
            ('coins_per_share_change', 'change in coins per diluted share'),
            ('coins_per_share_change_first_order', 'first-order approximation to change in coins per diluted share'),
            ('effect_bps_of_coins_per_share', 'effect in basis points'), ('value_to_common_usd', 'value to common USD')]


def evidence_items(result, call_index):
    """Only reviewed result records can become answer evidence; audit/history never become claims."""
    catalog = {}
    prefix = 'c' + str(call_index) + '.'
    company = result.get('context', {}).get('company', {}).get('ticker') or result.get('firm', {}).get('ticker', '')

    def add(key, row, text, urls, path, displayed_fields):
        if row.get("provenance", {}).get("price_date"):
            text += " Market-price date: " + row["provenance"]["price_date"] + "."
        warnings = _warnings(result, row)
        text += ''.join(' Source: ' + url + '.' for url in dict.fromkeys(urls))
        if warnings:
            text += ' Warnings: ' + '; '.join(warnings) + '.'
        catalog[prefix + key] = {"text": text, "path": path, "fields": tuple(displayed_fields)}

    for i, row in enumerate(result.get('results', [])):
        period = (row.get('fp', '') + ' ' if row.get('fp') not in (None, 'FY') else '') + 'FY' + str(row['fiscal_year'])
        text = company + ' ' + period + ' ' + LABELS[row['metric']].lower() + ': '
        if row['status'] == 'ok':
            text += row.get('display_value', row['value']) + ('%' if row['unit'] == 'percent' else ' USD')
            text += ' (' + row['period_start'] + ' to ' + row['period_end'] + ').'
            sources = [row] if 'source_url' in row else row.get('inputs', [])
            add('r' + str(i), row, text, [r['source_url'] for r in sources if 'source_url' in r], ('results', i), ('value', 'display_value'))
        else:
            add('r' + str(i), row, text + 'unavailable (' + row['reason'] + ').', [], ('results', i), ())
    def add_fields(key, row, heading, definitions, urls, path):
        for field, label in definitions:
            if row.get(field) is not None:
                value = ('yes' if row[field] else 'no') if isinstance(row[field], bool) else row[field]
                add(key + '.' + field, row, heading + ': ' + label + ': ' + value + '.', urls, path, (field,))

    for i, row in enumerate(result.get('actions', [])):
        # Fixed field labels preserve sign, basis and the association between each number and its measure.
        fields = [('usd', 'amount USD'), ('coins_per_share_change', 'change in coins per diluted share'),
                  ('effect_bps_of_coins_per_share', 'effect in basis points'), ('value_to_common_usd', 'value to common USD')]
        details = '; '.join(label + ': ' + row[key] for key, label in fields if row.get(key) is not None)
        add('a' + str(i), row, company + ' ' + row['action'] + ' (' + row.get('basis', 'filed') + '), week ending '
            + row['week_end'] + ': ' + details + '.', [row['provenance']['filing_url']], ('actions', i), [field for field, _ in fields])
        definitions = fields_action(row)
        heading = (company + ' ' + row['action'] + ' (' + row.get('basis', 'filed') + '), week ending ' + row['week_end'])
        add_fields('a' + str(i), row, heading, definitions, [row['provenance']['filing_url']], ('actions', i))
    if result.get('week'):
        rows = [('week', result['week'])]
        if result.get('comparison'):
            rows.append(('comparison', result['comparison']['week']))
        for key, row in rows:
            path = ('week',) if key == 'week' else ('comparison', 'week')
            add(key, row, company + ' week ending ' + row['week_end'] + ': ' + row['coins_per_share'] + ' '
                + row['coins_per_share_unit'] + '.', [row['provenance']['filing_url']], path, ('coins_per_share',))
            definitions = [('coins_per_share', row['coins_per_share_unit']), ('net_sats_per_share', 'net sats per diluted share'),
                           ('net_mnav', 'net mNAV'), ('coin_price_usd', row['coin'] + ' price USD'),
                           ('share_price_usd', 'common share price USD'), ('diluted_shares', 'diluted shares'),
                           ('coin_holdings', row['coin'] + ' holdings'), ('preferred_close_usd', 'preferred close USD')]
            add_fields(key, row, company + ' week ending ' + row['week_end'], definitions, [row['provenance']['filing_url']], path)
        if result.get('comparison'):
            other, row = result['comparison'], result['week']
            text = (company + ' change from ' + other['week']['week_end'] + ' to ' + row['week_end'] + ': '
                    + other['change_coins_per_share'] + ' ' + row['coins_per_share_unit'] + '; ' + other['change_percent'] + '%.')
            urls = [row['provenance']['filing_url'], other['week']['provenance']['filing_url']]
            add('change', {}, text, urls, ('comparison',), ('change_coins_per_share', 'change_percent'))
            add_fields('change', other, company + ' change from ' + other['week']['week_end'] + ' to ' + row['week_end'],
                   [('change_coins_per_share', row['coins_per_share_unit']), ('change_percent', 'change percent')], urls, ('comparison',))
    if result.get('break_even'):
        row = result['break_even']
        add('break_even', row, company + ' ' + row['preferred'] + ' week ending ' + row['week_end']
            + ': break-even price ' + row['break_even_price_usd'] + ' USD; preferred close ' + row['preferred_close_usd']
            + ' USD. ' + row['adds_while'] + '.', [row['provenance']['filing_url']], ('break_even',), ('break_even_price_usd', 'preferred_close_usd', 'adds_while'))
        heading = company + ' ' + row['preferred'] + ' week ending ' + row['week_end']
        definitions = [('liquidation_preference_usd', 'liquidation preference USD'), ('net_mnav', 'net mNAV'),
                       ('break_even_price_usd', 'break-even price USD'), ('preferred_close_usd', 'preferred close USD'),
                       ('gap_usd', 'preferred close minus break-even USD'), ('adds_at_close', 'adds coins per share at recorded close'),
                       ('rotation', 'rotation'), ('adds_while', 'adds coins per share while')]
        add_fields('break_even', row, heading, definitions, [row['provenance']['filing_url']], ('break_even',))
    return catalog


def evidence_catalog(result, call_index):
    """Model-facing IDs and text; record/field bindings remain application-owned."""
    return {key: item["text"] for key, item in evidence_items(result, call_index).items()}


def render_selection(selection, catalog):
    """Validate the untrusted selection at the model boundary, then render trusted text."""
    if (not isinstance(selection, dict) or set(selection) != {'evidence'} or not isinstance(selection['evidence'], list)
            or not 1 <= len(selection['evidence']) <= 40
            or any(not isinstance(key, str) or key not in catalog for key in selection['evidence'])):
        raise ValueError('Reply with {"evidence": ["<id from answer_evidence>"]}; select only existing evidence IDs.')
    return '\n\n'.join(catalog[key] for key in dict.fromkeys(selection['evidence']))
