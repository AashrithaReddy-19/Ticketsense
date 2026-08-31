import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, tokenStore, type User } from "../api/client";

type AuthValue = { user:User|null; loading:boolean; login:(email:string,password:string)=>Promise<User>; logout:()=>Promise<void>; hasPermission:(permission:string)=>boolean };
const AuthContext=createContext<AuthValue|null>(null);

export function AuthProvider({children}:{children:ReactNode}) {
  const [user,setUser]=useState<User|null>(null); const [loading,setLoading]=useState(true);
  async function load(){if(!tokenStore.get()){setLoading(false);return}try{setUser(await api.me())}catch{tokenStore.clear();setUser(null)}finally{setLoading(false)}}
  useEffect(()=>{load();const unauthorized=()=>{setUser(null);setLoading(false)};window.addEventListener("ticketsense:unauthorized",unauthorized);return()=>window.removeEventListener("ticketsense:unauthorized",unauthorized)},[]);
  async function login(email:string,password:string){await api.login(email,password);const current=await api.me();setUser(current);return current}
  async function logout(){await api.logout();setUser(null)}
  const hasPermission=(permission:string)=>Boolean(user?.permissions.includes(permission));
  return <AuthContext.Provider value={{user,loading,login,logout,hasPermission}}>{children}</AuthContext.Provider>
}
export function useAuth(){const value=useContext(AuthContext);if(!value)throw new Error("useAuth must be inside AuthProvider");return value}
