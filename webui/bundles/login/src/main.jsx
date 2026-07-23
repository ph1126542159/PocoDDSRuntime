import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, ArrowRight, KeyRound, ShieldCheck, UserRound } from "lucide-react";
import "./styles.css";

function Login() {
  const [user, setUser] = useState("admin");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async event => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/topology", { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error(response.status === 401 ? "管理令牌无效" : "无法连接运行时");
      sessionStorage.setItem("pdr.webui.token", token);
      sessionStorage.setItem("pdr.webui.user", user);
      window.parent.postMessage({ type: "pdr-authenticated" }, window.location.origin);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  return <main><section className="intro"><div className="brand"><span><Activity size={22} /></span><b>PocoDDS Runtime</b></div>
    <div className="intro-copy"><small>MODULAR RUNTIME CONSOLE</small><h1>简单管理，<br />清晰掌控。</h1>
      <p>每个功能都是独立 Bundle，可按需安装、升级与卸载。</p></div>
    <div className="secure"><ShieldCheck size={18} /><span><b>本地安全访问</b><small>Bearer Token protected</small></span></div>
  </section><section className="form-side"><form onSubmit={submit}><div className="form-title"><span><KeyRound size={19} /></span><h2>登录管理后台</h2><p>请输入运行时管理凭据</p></div>
    <label>用户名<div><UserRound size={17} /><input value={user} onChange={e => setUser(e.target.value)} autoComplete="username" /></div></label>
    <label>管理令牌<div><KeyRound size={17} /><input type="password" value={token} onChange={e => setToken(e.target.value)}
      placeholder="Bearer Token" autoComplete="current-password" /></div></label>
    {error && <p className="error">{error}</p>}
    <button disabled={busy || !token}>{busy ? "正在验证…" : "进入控制台"}<ArrowRight size={17} /></button>
    <small className="hint">令牌仅保存在当前浏览器会话中</small></form></section></main>;
}
createRoot(document.getElementById("root")).render(<Login />);
