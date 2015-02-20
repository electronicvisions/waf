// Thomas Nagy, 2015

import java.util.HashMap;
import java.util.Map;
import java.util.Arrays;
import java.util.List;
import java.util.Date;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Collections;
import java.util.Scanner;
import java.lang.Math;
import java.lang.StringBuilder;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.File;
import java.io.StringWriter;
import java.io.PrintWriter;

import java.lang.Math;
import com.eclipsesource.json.JsonObject;
import com.eclipsesource.json.JsonArray;

import java.lang.ProcessBuilder;
import java.lang.ProcessBuilder.Redirect;
import java.lang.Process;

import java.io.FileOutputStream;
import java.net.ServerSocket;
import java.net.Socket;

public class Prefork implements Runnable, Comparator<Object[]> {
	private static int HEADER_SIZE = 64;
	private static int BUF = 2048;
	static String SHARED_KEY = "";

	private Socket sock = null;
	private int port = 0;

	public Prefork(Socket sock, int port) {
		this.sock = sock;
		this.port = port;
	}

	public boolean safeCompare(String a, String b) {
		int sum = Math.abs(a.length() - b.length());
		for (int i = 0; i < b.length(); ++i) {
			sum |= a.charAt(i) ^ b.charAt(i);
		}
		return sum == 0;
	}

	public void run ()
	{
		try {
			if (sock != null)
			{
				while (true) {
					InputStream in = sock.getInputStream();
					OutputStream out = sock.getOutputStream();

					byte b[] = new byte[HEADER_SIZE];
					int off = 0;
					while (off < b.length) {
						int c = in.read(b, off, b.length - off);
						if (c <= 0) {
							throw new RuntimeException("Connection closed too early");
						}
						off += c;
					}

					String line = new String(b);
					String key = line.substring(line.length() - 20);
					if (key.length() != 20) {
						System.err.println("Fatal error in the application");
					}
					if (!safeCompare(key, SHARED_KEY))
					{
						System.err.println("Invalid key given " + key.length() + " " + SHARED_KEY.length() + "  " + key + " " + SHARED_KEY);
						sock.close();
					}

					//System.out.println(new String(b));
					String[] args = line.substring(0, line.length() - 20).split(",");
					if (args[0].equals("REQ")) {
						process(args, sock);
					}
					else
					{
						System.out.println("Invalid command " + new String(b) + " on port " + this.port);
						sock.close();
						break;
					}
				}
			} else {
				// magic trick to avoid creating a new inner class
				ServerSocket server = new ServerSocket(port);
				server.setReuseAddress(true);
				while (true) {
					Socket conn = server.accept();
					conn.setTcpNoDelay(true);
					Prefork tmp = new Prefork(conn, port);
					Thread t = new Thread(tmp);
					t.start();
				}
			}
		} catch (InterruptedException e) {
			e.printStackTrace();
		} catch (IOException e) {
			e.printStackTrace();
		}
	}

	public String make_out(Socket sock, String stdout, String stderr, String exc) {
		if ((stdout == null || stdout.length() == 0) && (stderr == null || stderr.length() == 0) && (exc == null || exc.length() == 0))
		{
			return null;
		}

		JsonArray ret = new JsonArray();
		ret.add(stdout);
		ret.add(stderr);
		ret.add(exc);
		return ret.toString();
	}

	public String readFile(File f) throws IOException {
		String ret = new Scanner(f).useDelimiter("\\A").next();
		return ret;
	}

	public void process(String[] args, Socket sock) throws IOException, InterruptedException {
		long size = new Long(args[1].trim());
		//System.out.println("" + args[1] + " " + args[2] + " " + args[3] + " " + args.length);

		byte[] buf = new byte[BUF];
		StringBuilder sb = new StringBuilder();
		InputStream in = sock.getInputStream();
		long cnt = 0;
		while (cnt < size) {
			int c = in.read(buf, 0, (int) Math.min(BUF, size-cnt));
			if (c <= 0) {
				throw new RuntimeException("Connection closed too early");
			}
			sb.append(new String(buf, 0, c));
			cnt += c;
		}

		String stdout = null;
		String stderr = null;
		String exc = null;

		JsonObject kw = JsonObject.readFrom(sb.toString());
		boolean isShell = kw.get("shell").asBoolean();

		String[] command = null;

		if (isShell) {
			command = new String[] {"sh", "-c", kw.get("cmd").asString()};
		}
		else
		{
			JsonArray arr = kw.get("cmd").asArray();
			int siz = arr.size();
			command = new String[siz];
			for (int i =0; i < siz; ++i) {
				command[i] = arr.get(i).asString();
			}
		}

		ProcessBuilder pb = new ProcessBuilder(command);
		String cwd = kw.get("cwd").asString();
		if (cwd != null) {
			pb.directory(new File(cwd));
		}

		long threadId = Thread.currentThread().getId();
		String errFile = "log_err_" + threadId;
		File elog = new File(errFile);
		pb.redirectError(Redirect.to(elog));

		String outFile = "log_out_" + threadId;
		File olog = new File(outFile);
		pb.redirectOutput(Redirect.to(olog));

		int status = -8;
		try {
			Process p = pb.start();
			status = p.waitFor();
		} catch (IOException e) {
			StringWriter sw = new StringWriter();
			e.printStackTrace(new PrintWriter(sw));
			exc = sw.toString();
		}

		if (olog.length() != 0) {
			stdout = readFile(olog);
		}
		olog.delete();

		if (elog.length() != 0) {
			stderr = readFile(elog);
		}
		elog.delete();

		OutputStream out = sock.getOutputStream();
		String msg = make_out(sock, stdout, stderr, exc);

		// RES, status, ret size
		int len = msg != null ? msg.length() : 0;

		String ret = String.format("%-64s", String.format("RES,%d,%d", status, len));
		out.write(ret.getBytes());
		if (len > 0)
		{
			out.write(msg.getBytes());
		}
	}

	public int compare(Object[] a, Object[] b) {
		return ((Long) a[0]).compareTo((Long) b[0]);
	}

	public static void main(String[] args) {
		Map<String, String> env = System.getenv();
		SHARED_KEY = env.get("SHARED_KEY");
		Prefork tmp = new Prefork(null, new Integer(args[0]));
		tmp.run();
	}
}

