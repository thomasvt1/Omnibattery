import { test } from 'node:test';
import assert from 'node:assert/strict';
let Panel;
globalThis.HTMLElement = class { attachShadow() { this.shadowRoot = {}; } };
globalThis.customElements = {get() {}, define(name,cls) {Panel=cls;}};
await import('../../custom_components/omnibattery/frontend/marstek-panel.js');
function panel(service) {
  const p = new Panel();
  p._hass = {states: {'number.test': {state:'12'}}, callService: service};
  p._commandFeedback = (kind,text) => {p.feedback = {kind,text};};
  p._t = (key,vars) => key + (vars?.error || '');
  p._update = () => {};
  return p;
}
function control() {return {value:'80', __pendingValue:80, setAttribute(){},removeAttribute(){},dispatchEvent(){}};}
test('rejected command clears optimism and restores actual value',async()=>{
 const p=panel(async()=>{throw Error('Denied');}), c=control();
 assert.equal(await p._sendCommand('number','set_value',{entity_id:'number.test'},c),false);
 assert.equal(c.value,'12'); assert.equal(c.__pendingValue,undefined);
 assert.equal(c.disabled,false); assert.equal(p.feedback.kind,'failed');
 assert.match(p.feedback.text,/Denied/);
});
test('duplicate pending command is suppressed and success means accepted',async()=>{
 let finish, calls=0;
 const p=panel(()=>{calls++;return new Promise(r=>{finish=r;});}),c=control();
 const first=p._sendCommand('number','set_value',{entity_id:'number.test'},c);
 assert.equal(c.disabled,true);
 assert.equal(await p._sendCommand('number','set_value',{entity_id:'number.test'},c),false);
 finish(); assert.equal(await first,true); assert.equal(calls,1);
 assert.equal(p.feedback.kind,'accepted'); assert.equal(c.disabled,false);
});
