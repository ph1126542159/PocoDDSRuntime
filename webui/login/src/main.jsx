import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, ArrowRight, KeyRound, ShieldCheck, UserRound } from "lucide-react";
import "./styles.css";

const LOCAL_USERNAME = "admin";
const LOCAL_PASSWORD = "admin";

function Login() {
  const [user, setUser] = useState(LOCAL_USERNAME);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = event => {
    event.preventDefault();
    setBusy(true); setError("");
    if (user !== LOCAL_USERNAME || password !== LOCAL_PASSWORD) {
      setError("用户名或密码错误");
      setBusy(false);
      return;
    }
    sessionStorage.removeItem("pdr.webui.token");
    sessionStorage.setItem("pdr.webui.user", user);
    window.location.assign("/home/");
  };
  return <main><section className="intro"><div className="brand"><span><Activity size={22} /></span><b>PocoDDS Runtime</b></div>
    <div className="intro-copy"><small>MODULAR RUNTIME CONSOLE</small><h1>简单管理，<br />清晰掌控。</h1>
      <p>每个功能都是独立 Bundle，可按需安装、升级与卸载。</p></div>
    <div className="secure"><ShieldCheck size={18} /><span><b>本地管理访问</b><small>仅监听 127.0.0.1</small></span></div>
  </section><section className="form-side"><form onSubmit={submit}><div className="form-title"><span><KeyRound size={19} /></span><h2>登录管理后台</h2><p>请输入运行时管理凭据</p></div>
    <label>用户名<div><UserRound size={17} /><input value={user} onChange={e => setUser(e.target.value)} autoComplete="username" /></div></label>
    <label>密码<div><KeyRound size={17} /><input type="password" value={password} onChange={e => setPassword(e.target.value)}
      placeholder="请输入密码" autoComplete="current-password" /></div></label>
    {error && <p className="error">{error}</p>}
    <button disabled={busy || !password}>{busy ? "正在验证…" : "进入控制台"}<ArrowRight size={17} /></button>
    <small className="hint">本地默认账号：admin / admin</small></form></section></main>;
}
createRoot(document.getElementById("root")).render(<Login />);
