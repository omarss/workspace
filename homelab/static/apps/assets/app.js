'use strict';

const TAG_CLASS = {
    feat: 'tag-feat', fix: 'tag-fix', break: 'tag-break',
};
const TAG_LABELS = new Set([
    'feat', 'fix', 'break', 'chore', 'docs', 'refactor', 'test', 'perf', 'build', 'ci', 'style',
]);

function fmtBytes(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
}

function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toISOString().slice(0, 10);
}

function shortSha(sha) {
    if (!sha) return '';
    return sha.slice(0, 12);
}

function classify(line) {
    const m = /^(feat|fix|chore|docs|refactor|test|perf|build|ci|style)(\(.+\))?(!)?:\s*(.*)$/.exec(line);
    if (m) {
        const breaking = m[3] === '!';
        return { tag: breaking ? 'break' : m[1], text: m[4] };
    }
    if (/^break|^breaking change/i.test(line)) {
        return { tag: 'break', text: line.replace(/^break(ing change)?:?\s*/i, '') };
    }
    return { tag: 'other', text: line };
}

function el(tag, props, ...children) {
    const node = document.createElement(tag);
    if (props) {
        for (const [k, v] of Object.entries(props)) {
            if (v == null) continue;
            if (k === 'class') node.className = v;
            else if (k === 'text') node.textContent = v;
            else if (k.startsWith('aria-') || k === 'role') node.setAttribute(k, v);
            else node[k] = v;
        }
    }
    for (const c of children) {
        if (c == null) continue;
        node.append(c);
    }
    return node;
}

function renderChangelogItem(line) {
    const c = classify(line);
    const li = el('li');
    if (TAG_LABELS.has(c.tag)) {
        li.append(el('span', { class: 'tag ' + (TAG_CLASS[c.tag] || 'tag-other'), text: c.tag }));
    } else {
        li.append(el('span', { class: 'tag tag-other', text: 'other' }));
    }
    li.append(el('span', { text: c.text }));
    return li;
}

function renderRelease(rel) {
    const wrap = el('div', { class: 'release' });

    const head = el('div', { class: 'release-head' });
    head.append(el('span', { class: 'release-version', text: 'v' + rel.version }));
    head.append(el('span', {
        class: 'release-date',
        text: fmtDate(rel.released_at) + ' · ' + fmtBytes(rel.size_bytes),
    }));
    if (rel.apk) {
        head.append(el('a', {
            class: 'release-link',
            href: '/' + rel.apk,
            text: 'download',
            rel: 'noreferrer',
        }));
    }
    wrap.append(head);

    if (rel.sha256) {
        const sha = el('div', { class: 'sha', title: rel.sha256 });
        sha.textContent = 'sha256:' + rel.sha256;
        wrap.append(sha);
    }

    if (rel.changelog && rel.changelog.length) {
        const ul = el('ul', { class: 'changelog' });
        for (const line of rel.changelog) ul.append(renderChangelogItem(line));
        wrap.append(ul);
    }

    return wrap;
}

function renderApp(id, app) {
    const latest = app.latest || (app.releases && app.releases[0]) || {};
    const releases = app.releases || [];
    const latestApk = latest.apk || (id + '.latest.apk');

    const article = el('article', { class: 'app' });

    const head = el('div', { class: 'app-head' });
    const icon = el('img', {
        class: 'app-icon',
        src: '/icons/' + id + '.svg',
        alt: '',
        width: 56,
        height: 56,
        loading: 'lazy',
    });
    icon.addEventListener('error', () => { icon.style.visibility = 'hidden'; });
    head.append(icon);

    const headText = el('div', { class: 'app-head-text' });
    headText.append(el('h2', { class: 'app-name', text: app.name || id }));
    headText.append(el('div', { class: 'app-version', text: 'v' + (latest.version || '?') }));
    head.append(headText);

    article.append(head);

    if (app.description) {
        article.append(el('p', { class: 'app-desc', text: app.description }));
    }

    const actions = el('div', { class: 'actions' });
    actions.append(el('a', {
        class: 'download',
        href: '/' + id + '.latest.apk',
        text: 'Download latest',
        rel: 'noreferrer',
    }));
    actions.append(el('span', {
        class: 'meta',
        text: fmtBytes(latest.size_bytes) + ' · ' + fmtDate(latest.released_at),
    }));
    article.append(actions);

    if (latest.sha256) {
        article.append(el('div', {
            class: 'sha',
            title: latest.sha256,
            text: 'sha256:' + latest.sha256,
        }));
    }

    if (releases.length) {
        const details = el('details', { open: releases.length <= 1 });
        const count = releases.length;
        details.append(el('summary', { text: count + ' release' + (count === 1 ? '' : 's') }));
        for (const r of releases) details.append(renderRelease(r));
        article.append(details);
    }

    return article;
}

async function load() {
    const root = document.getElementById('apps');
    try {
        const res = await fetch('/manifest.json', { cache: 'no-store' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const apps = data.apps || {};
        const ids = Object.keys(apps).sort();

        root.replaceChildren();
        if (ids.length === 0) {
            const empty = el('div', { class: 'empty' });
            empty.append(document.createTextNode('No apps published yet. Run '));
            empty.append(el('code', { text: 'make release' }));
            empty.append(document.createTextNode(' from a project to publish here.'));
            root.append(empty);
        } else {
            for (const id of ids) root.append(renderApp(id, apps[id]));
        }

        const stamp = document.getElementById('generated');
        if (stamp && data.generated_at) {
            stamp.textContent = 'updated ' + fmtDate(data.generated_at);
        }
    } catch (err) {
        root.replaceChildren();
        const box = el('div', { class: 'error' });
        box.append(document.createTextNode('Failed to load '));
        box.append(el('code', { text: '/manifest.json' }));
        box.append(document.createTextNode(': ' + (err && err.message || 'unknown error')));
        root.append(box);
    }
}

load();
