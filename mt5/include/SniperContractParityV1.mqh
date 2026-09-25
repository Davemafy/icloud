#ifndef __SNIPER_CONTRACT_PARITY_V1_MQH__
#define __SNIPER_CONTRACT_PARITY_V1_MQH__

// Master Sniper contract parity v1.
// DEMO / PAPER ONLY until end-to-end parity release gates pass.

#define TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"

string TZ_SniperTrim(const string value)
{
   string out=value;
   StringTrimLeft(out);
   StringTrimRight(out);
   return out;
}

string TZ_SniperCanonicalRisk(const double value)
{
   return DoubleToString(value,8);
}

string TZ_SniperCanonicalContract(
   const string analysis_id,const string zone_id,const string direction,
   const string current_grade,const int qualified_mitigations,
   const string risk_context,const double base_risk_pct,
   const string execution_authority)
{
   return "analysis_id="+TZ_SniperTrim(analysis_id)+
      "|zone_id="+TZ_SniperTrim(zone_id)+
      "|direction="+TZ_SniperTrim(direction)+
      "|current_grade="+TZ_SniperTrim(current_grade)+
      "|qualified_mitigations="+IntegerToString(qualified_mitigations)+
      "|risk_context="+TZ_SniperTrim(risk_context)+
      "|base_risk_pct="+TZ_SniperCanonicalRisk(base_risk_pct)+
      "|execution_authority="+TZ_SniperTrim(execution_authority);
}

uint TZ_SniperROR(const uint x,const int n)
{
   return (x>>n)|(x<<(32-n));
}

string TZ_SniperSHA256(const string text)
{
   uchar msg[];
   int n=StringToCharArray(text,msg,0,-1,CP_UTF8);
   if(n>0 && msg[n-1]==0) n--;
   ulong bitlen=(ulong)n*8;
   int total=n+1+8;
   int rem=total%64;
   if(rem!=0) total+=(64-rem);
   ArrayResize(msg,total);
   msg[n]=0x80;
   for(int i=n+1;i<total;i++) msg[i]=0;
   for(int i=0;i<8;i++) msg[total-1-i]=(uchar)((bitlen>>(8*i))&0xff);

   uint h0=0x6a09e667,h1=0xbb67ae85,h2=0x3c6ef372,h3=0xa54ff53a;
   uint h4=0x510e527f,h5=0x9b05688c,h6=0x1f83d9ab,h7=0x5be0cd19;
   uint k[64]={
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

   uint w[64];
   for(int off=0;off<total;off+=64)
   {
      for(int t=0;t<16;t++)
      {
         int p=off+t*4;
         w[t]=((uint)msg[p]<<24)|((uint)msg[p+1]<<16)|((uint)msg[p+2]<<8)|(uint)msg[p+3];
      }
      for(int t=16;t<64;t++)
      {
         uint s0=TZ_SniperROR(w[t-15],7)^TZ_SniperROR(w[t-15],18)^(w[t-15]>>3);
         uint s1=TZ_SniperROR(w[t-2],17)^TZ_SniperROR(w[t-2],19)^(w[t-2]>>10);
         w[t]=w[t-16]+s0+w[t-7]+s1;
      }
      uint a=h0,b=h1,c=h2,d=h3,e=h4,f=h5,g=h6,h=h7;
      for(int t=0;t<64;t++)
      {
         uint S1=TZ_SniperROR(e,6)^TZ_SniperROR(e,11)^TZ_SniperROR(e,25);
         uint ch=(e&f)^((~e)&g);
         uint temp1=h+S1+ch+k[t]+w[t];
         uint S0=TZ_SniperROR(a,2)^TZ_SniperROR(a,13)^TZ_SniperROR(a,22);
         uint maj=(a&b)^(a&c)^(b&c);
         uint temp2=S0+maj;
         h=g; g=f; f=e; e=d+temp1; d=c; c=b; b=a; a=temp1+temp2;
      }
      h0+=a; h1+=b; h2+=c; h3+=d; h4+=e; h5+=f; h6+=g; h7+=h;
   }
   return StringFormat("%08x%08x%08x%08x%08x%08x%08x%08x",h0,h1,h2,h3,h4,h5,h6,h7);
}

string TZ_SniperContractFingerprint(
   const string analysis_id,const string zone_id,const string direction,
   const string current_grade,const int qualified_mitigations,
   const string risk_context,const double base_risk_pct,
   const string execution_authority)
{
   return TZ_SniperSHA256(TZ_SniperCanonicalContract(
      analysis_id,zone_id,direction,current_grade,qualified_mitigations,
      risk_context,base_risk_pct,execution_authority));
}

#endif
