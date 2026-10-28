const $ = s => document.querySelector(s);
let reservations = [];
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Erro de comunicação.');
  return result;
}
function message(text, error=false) { $('#message').textContent = text; $('#message').className = error ? 'error' : 'success'; }
function resetForm() { $('#reservation').reset(); $('#reservation-id').value=''; $('#form-title').textContent='Nova reserva'; }
async function refresh() {
  const data = await api('/api/reservations'); reservations = data.reservations;
  const list = $('#list'); list.replaceChildren();
  if (!reservations.length) { list.textContent='Nenhuma reserva encontrada.'; return; }
  reservations.forEach(row => {
    const card = document.createElement('div'); card.className='device';
    const info = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = row.name || 'Sem nome';
    const detail = document.createElement('p'); detail.textContent = `${row.mac} · ${row.ip}`;
    const edit = document.createElement('button'); edit.type='button'; edit.textContent='Editar';
    edit.addEventListener('click', () => { $('#reservation-id').value=row.id; $('#mac').value=row.mac; $('#ip').value=row.ip; $('#name').value=row.name; $('#form-title').textContent='Editar reserva'; $('#mac').focus(); });
    info.append(title, detail); card.append(info, edit); list.append(card);
  });
}
$('#connect').addEventListener('submit', async e => {
  e.preventDefault(); message('Conectando...');
  try { await api('/api/login',{address:$('#address').value,username:$('#username').value,password:$('#password').value}); $('#password').value=''; await refresh(); $('#login').hidden=true; $('#dashboard').hidden=false; message('Conectado.'); }
  catch(err) { $('#password').value=''; message(err.message,true); }
});
$('#reservation').addEventListener('submit', async e => {
  e.preventDefault(); message('Salvando reserva...');
  try {
    const mac=$('#mac').value.trim().toLowerCase();
    const id=$('#reservation-id').value, ip=$('#ip').value.trim();
    const old=reservations.find(row => row.id===id);
    if (!old || old.mac!==mac || old.ip!==ip) await api('/api/reservation',{id, mac, ip});
    try { await api('/api/name',{mac,name:$('#name').value}); } catch(err) { message('Reserva salva, mas o nome local não foi salvo: '+err.message,true); await refresh(); return; }
    resetForm(); await refresh(); message('Dados salvos.');
  } catch(err) { message(err.message,true); }
});
$('#cancel').addEventListener('click',resetForm);
$('#refresh').addEventListener('click',async()=>{try{await refresh();message('Lista atualizada.')}catch(err){message(err.message,true)}});
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{});}finally{$('#dashboard').hidden=true;$('#login').hidden=false;resetForm();message('Sessão encerrada.')}});
