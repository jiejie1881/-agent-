// Stop with an explicit error instead of silently truncating business data.
export async function allPages<T>(fetchPage: (params: {offset:number;limit:number}) => Promise<{data:T[]}>): Promise<{data:T[]}> {
  const result:T[]=[]
  for(let offset=0;offset<10000;offset+=100){const {data}=await fetchPage({offset,limit:100});result.push(...data);if(data.length<100)return {data:result}}
  throw new Error('记录超过当前页面支持范围，请使用服务端分页查询')
}
